# Save this file as resolve_duplicates_by_cluster.py
import asyncio
import os
import json
from collections import defaultdict
from playwright.async_api import async_playwright, APIRequestContext
from google import genai
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
AUTH_FILE = "auth.json"
HEADERS_FILE = "headers.json"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY not found.")
client = genai.Client(api_key=GEMINI_API_KEY)
REVIEW_ID = os.getenv("REVIEW_ID")
if not REVIEW_ID: raise ValueError("REVIEW_ID not found.")

# --- AI & RESOLUTION FUNCTIONS (Unchanged, they are still perfect) ---

async def are_abstracts_duplicates(abstract1: str, abstract2: str) -> tuple[bool, str]:
    if not abstract1 or not abstract2:
        return False, "One or both abstracts were missing."
    prompt = f"""
    You are an expert academic researcher. Your task is to determine if the two abstracts below describe the exact same study.
    Focus on the core methodology, population, results, and conclusions. Ignore minor formatting or wording differences.
    Respond ONLY with a JSON object with two keys: "is_duplicate" (boolean) and "reason" (a brief string explanation).
    Abstract 1: --- {abstract1} ---
    Abstract 2: --- {abstract2} ---
    """
    print("      [AI] Analyzing abstracts for duplication...")
    try:
        response = await asyncio.to_thread(client.models.generate_content, model="gemini-2.0-flash-lite", contents=prompt)
        if response.text is None: return False, "AI returned no response."
        json_response_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        decision = json.loads(json_response_text)
        return decision.get("is_duplicate", False), decision.get("reason", "No reason provided.")
    except Exception as e:
        print(f"      [AI_ERROR] Failed to get decision from Gemini AI: {e}")
        return False, "AI analysis failed."

async def resolve_duplicate_status(api_context: APIRequestContext, review_id: str, article_to_resolve_id: int, is_duplicate: bool):
    action = 1 if is_duplicate else 2
    action_text = "DUPLICATE" if is_duplicate else "NOT A DUPLICATE"
    print(f"      -> Resolving article {article_to_resolve_id} as: {action_text}")
    url = f"https://rayyan.ai/api/v1/reviews/{review_id}/duplicates/{article_to_resolve_id}"
    payload = {"duplicate_action": action, "isDeletedArticle": False}
    try:
        response = await api_context.patch(url, data=payload)
        if not response.ok: print(f"      [ERROR] Failed to resolve status for {article_to_resolve_id}: {response.status} {await response.text()}")
    except Exception as e: print(f"      [ERROR] An exception occurred while resolving status: {e}")

# --- NEW FETCH FUNCTION ---

async def fetch_all_unresolved_duplicates(api_context: APIRequestContext, review_id: str):
    """Fetches ALL unresolved duplicates in one go."""
    print("--- Step 1: Fetching the master list of all unresolved duplicates ---")
    url = f"https://rayyan.ai/api/v1/reviews/{review_id}/results"
    # To get all results, we can omit 'length' or set it to a very high number.
    # Setting a high number is safer in case the API has a default page size.
    payload = {
        "start": 0,
         # Fetch up to 5000 articles"length": 5000,
        "return_filtered_total": "false",
        "extra": {"dedup_result": 0}
    }
    try:
        response = await api_context.fetch(url, method="SEARCH", data=payload)
        if response.ok:
            return await response.json()
        else:
            print(f"Failed to fetch master list. Status: {response.status} {await response.text()}")
            return None
    except Exception as e:
        print(f"An exception occurred while fetching the master list: {e}")
        return None

# --- MAIN ORCHESTRATION (Completely Rewritten for the new strategy) ---
async def main():
    if not os.path.exists(AUTH_FILE) or not os.path.exists(HEADERS_FILE):
        print("❌ FATAL: `auth.json` or `headers.json` not found. Run `setup_and_capture.py` first.")
        return

    async with async_playwright() as p:
        with open(HEADERS_FILE, "r") as f:
            headers = json.load(f)
        
        api_context = await p.request.new_context(
            storage_state=AUTH_FILE,
            extra_http_headers=headers
        )

        master_list_data = await fetch_all_unresolved_duplicates(api_context, str(REVIEW_ID))

        if not master_list_data or not master_list_data.get("data"):
            print("✅ No unresolved duplicates found. All done!")
            await api_context.dispose()
            return

        all_articles = master_list_data.get("data", [])

        # Step 2: Group articles by their cluster_id
        print("\n--- Step 2: Grouping articles by cluster ID ---")
        clusters = defaultdict(list)
        for article in all_articles:
            cluster_id = article.get("dedup_results", {}).get("cluster_id")
            if cluster_id:
                clusters[cluster_id].append(article)
        
        print(f"✅ Found {len(all_articles)} articles across {len(clusters)} unique clusters.")

        # Step 3: Process each cluster
        print("\n--- Step 3: Processing each cluster one by one ---")
        for i, (cluster_id, articles_in_cluster) in enumerate(clusters.items()):
            print(f"\n--- Processing Cluster {i+1}/{len(clusters)} (ID: {cluster_id}) with {len(articles_in_cluster)} articles ---")

            if len(articles_in_cluster) < 2:
                print("   Skipping cluster with only one article.")
                continue

            # Pick the first article as the "anchor" to compare against
            anchor_article = articles_in_cluster[0]
            anchor_id = anchor_article.get("id")
            anchor_abstract_list = anchor_article.get("abstracts", [])
            anchor_abstract = anchor_abstract_list[0].get("content", "") if anchor_abstract_list else ""
            
            print(f"   Anchor Article ID: {anchor_id}")

            # Compare the anchor to every other article in the cluster
            for other_article in articles_in_cluster[1:]:
                other_id = other_article.get("id")
                other_abstract_list = other_article.get("abstracts", [])
                other_abstract = other_abstract_list[0].get("content", "") if other_abstract_list else ""
                
                print(f"\n   Comparing Anchor ({anchor_id}) vs. Other ({other_id})")

                is_dup, reason = await are_abstracts_duplicates(anchor_abstract, other_abstract)
                print(f"      [AI Decision] Is Duplicate: {is_dup}. Reason: {reason}")
                
                # Resolve the status of the 'other' article
                await resolve_duplicate_status(api_context, str(REVIEW_ID), other_id, is_dup)

                # Be a good API citizen
                await asyncio.sleep(5)
        
        await api_context.dispose()
        print("\n✅ All clusters have been processed. Script finished.")

if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import os
import json
from typing import Optional, Dict
from playwright.async_api import (
    async_playwright,
    APIRequestContext,
    BrowserContext,
    Page,
    Request,
)
from google import genai
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

AUTH_FILE = "auth.json"
HEADERS_FILE = "headers.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file.")
client = genai.Client(api_key=GEMINI_API_KEY)

RAYYAN_EMAIL = os.getenv("RAYYAN_EMAIL")
RAYYAN_PASSWORD = os.getenv("RAYYAN_PASSWORD")
REVIEW_ID = os.getenv("REVIEW_ID") # Make sure this matches your review "Long-Term Mortality and Major..."
if not RAYYAN_EMAIL or not RAYYAN_PASSWORD or not REVIEW_ID:
    raise ValueError("RAYYAN_EMAIL, RAYYAN_PASSWORD, or REVIEW_ID not found in .env file.")

# --- AI & ARTICLE PROCESSING FUNCTIONS ---

# --- CRITERIA UPDATED BASED ON YOUR PROSPERO PROTOCOL ---
INCLUSION_CRITERIA = """
I am screening for a systematic review and meta-analysis on aortic valve replacement.
Please adhere strictly to the following criteria based on the study protocol.

**PICO Framework:**
*   **Population:** Adult patients with severe aortic stenosis classified as being at **LOW SURGICAL RISK** (e.g., STS score < 4%).
*   **Intervention:** Transcatheter Aortic Valve Replacement (TAVR or TAVI).
*   **Comparator:** Surgical Aortic Valve Replacement (SAVR). The study MUST be a direct comparison between TAVR and SAVR.
*   **Outcomes:** Must report on long-term (>=1 year) clinical outcomes such as mortality, stroke, reintervention, or MACCE.

**Inclusion Criteria:**
1.  **Study Design:** Must be a **Randomized Controlled Trial (RCT)**.
2.  **Population:** Must explicitly state that the patient cohort is **low-risk**.
3.  **Comparison:** Must compare TAVR directly against SAVR.

**Exclusion Criteria:**
1.  **Wrong Study Design:** Exclude ALL non-RCTs. This includes observational studies, cohort studies, registry analyses, case series, case reports, editorials, letters, and especially **systematic reviews or meta-analyses**.
2.  **Wrong Population:** Exclude studies focused on intermediate-risk or high-risk patients. Exclude pediatric studies or studies on conditions other than aortic stenosis.
3.  **Wrong Comparison:** Exclude studies that do not compare TAVR vs. SAVR (e.g., TAVR only, SAVR only, TAVR vs. medical therapy, comparisons between different TAVR devices).
4.  **Wrong Outcomes:** Exclude studies that only report on procedural details, imaging, or economic analyses without clinical outcomes.
5.  **Animal studies.**
"""

def create_ai_prompt(article_title: str, article_abstract: str) -> str:
    """Creates the prompt to send to the Gemini API."""
    return f"""
    You are an expert assistant conducting a systematic review screening.
    Based on the provided inclusion and exclusion criteria, please analyze the following article's title and abstract.

    **Screening Criteria:**
    {INCLUSION_CRITERIA}

    ---
    **Article Title:** {article_title}
    **Article Abstract:** {article_abstract}
    ---

    **Your Task:**
    Decide if this article should be 'include' or 'exclude'.
    - If you decide to 'exclude', you MUST provide a concise, two-word reason (e.g., "Not RCT", "Wrong Population", "Review Article", "No Comparison", "High-Risk Patients").
    Respond ONLY with a valid JSON object in the following format:
    If including: {{"decision": "include", "reason": null}}
    If excluding: {{"decision": "exclude", "reason": "Your Two-Word Reason"}}
    """

async def get_ai_decision(article: dict) -> dict:
    """Gets a screening decision from the Gemini API for a single article."""
    title = article.get("title", "")
    abstract = ""
    if article.get("abstracts") and len(article["abstracts"]) > 0:
        abstract = article["abstracts"][0].get("content", "")

    if not title or not abstract:
        return {"decision": "exclude", "reason": "Missing Data"}
    
    # gemini-2.0-flash-lite (run first), gemini-2.5-pro-preview-06-05, gemini-1.5-flash, 

    prompt = create_ai_prompt(title, abstract)
    try:
        response = await asyncio.to_thread(
            client.models.generate_content, model="gemini-2.5-flash-lite-preview-06-17", contents=prompt
        )
        if response.text is None:
            print(f"   [AI_WARN] AI response text is None for article {article.get('id', 'N/A')}")
            return {"decision": "maybe", "reason": "AI Empty Response"}

        cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
        decision_json = json.loads(cleaned_response)

        if 'decision' in decision_json and decision_json['decision'] in ['include', 'exclude']:
            return decision_json
        else:
            print(f"   [AI_WARN] Invalid JSON from AI: {cleaned_response}")
            return {"decision": "maybe", "reason": "AI Format Error"}
    except Exception as e:
        print(f"   [AI_ERROR] Could not get AI decision for article {article['id']}: {e}")
        return {"decision": "maybe", "reason": "API Call Error"}

async def update_article_status(api_context: APIRequestContext, review_id: str, article_id: int, decision: str, reason: Optional[str] = None):
    """Updates an article's status on Rayyan (include, exclude, or maybe)."""
    url = f"https://rayyan.ai/api/v1/reviews/{review_id}/customize"
    payload = {"article_id": article_id, "plan": {}}

    if decision == "include":
        payload["plan"] = {"included": 1}
        print(f"   -> Including article {article_id}.")
    elif decision == "exclude":
        if reason:
            payload["plan"] = {f"__EXR__{reason}": 1}
            print(f"   -> Excluding article {article_id}. Reason: {reason}")
        else:
            payload["plan"] = {"included": -1}
            print(f"   -> Excluding article {article_id} (No reason provided).")
    elif decision == "maybe":
        payload["plan"] = {"included": 0}
        print(f"   -> Marking article {article_id} as 'Maybe'.")
    else:
        print(f"   [WARN] Unknown decision '{decision}'. Skipping update for article {article_id}.")
        return

    try:
        response = await api_context.post(url, data=payload)
        if not response.ok:
            print(f"   [ERROR] Failed to update article {article_id}: {response.status} {await response.text()}")
    except Exception as e:
        print(f"   [ERROR] An exception occurred while updating article {article_id}: {e}")

# --- SETUP & FETCH FUNCTIONS ---
async def fetch_undecided_articles(api_context: APIRequestContext, review_id: str, start: int, length: int = 100):
    url = f"https://rayyan.ai/api/v1/reviews/{review_id}/results"
    payload = {
        "start": start, "length": length, "order": {"0": {"dir": "asc"}},
        "return_filtered_total": "false", "extra": {"mode": "undecided"} # adjust to add/remove labels if needed , "user_labels": ["xxxx"]
    }
    try:
        return await api_context.fetch(url, method="SEARCH", data=payload)
    except Exception as e:
        print(f"An exception occurred while fetching articles: {e}")
        return None

async def perform_full_setup(playwright_instance, review_id: str):
    print("Performing full setup: Launching browser for login and header discovery.")
    browser = await playwright_instance.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    try:
        future = asyncio.get_running_loop().create_future()
        async def handle_request(request: Request):
            target_url_part = f"/api/v1/reviews/{review_id}/results"
            if request.method == "SEARCH" and target_url_part in request.url:
                print("Target API request intercepted!")
                headers = await request.all_headers()
                discovered_headers = {
                    key: value for key, value in headers.items()
                    if key.lower().startswith("x-") or key.lower() == "authorization"
                }
                if 'authorization' in (k.lower() for k in discovered_headers) and not future.done():
                    print(f"Discovered critical headers: {discovered_headers}")
                    future.set_result(discovered_headers)
        page.on("request", handle_request)
        await page.goto("https://new.rayyan.ai/")
        await page.get_by_role("textbox", name="Email").fill(str(RAYYAN_EMAIL))
        await page.get_by_role("textbox", name="Password").fill(str(RAYYAN_PASSWORD))
        await page.get_by_role("button", name="Sign In").click()
        await page.wait_for_load_state("networkidle")
        print("Login successful. Please navigate to your review manually.")
        print(f"Waiting to intercept API call for review ID: {review_id}...")
        # Manually navigate to the review in the browser to trigger the API call
        discovered_headers = await asyncio.wait_for(future, timeout=120) # Increased timeout
        with open(HEADERS_FILE, "w") as f:
            json.dump(discovered_headers, f)
        await context.storage_state(path=AUTH_FILE)
        print("Setup complete. Headers and auth state saved.")
    finally:
        await browser.close()


# --- MAIN ORCHESTRATION ---
async def main():
    headers = {}
    api_context = None
    async with async_playwright() as p:
        # --- Phase 1: Check if setup is needed ---
        should_run_setup = False
        if not os.path.exists(AUTH_FILE) or not os.path.exists(HEADERS_FILE):
            should_run_setup = True
        else:
            print("Found existing config files. Testing session validity...")
            with open(HEADERS_FILE, "r") as f:
                headers = json.load(f)
            api_context = await p.request.new_context(storage_state=AUTH_FILE, extra_http_headers=headers)
            assert REVIEW_ID is not None
            test_response = await fetch_undecided_articles(api_context, REVIEW_ID, 0, 1)
            if not test_response or test_response.status == 401:
                print(f"Session test failed (Status: {test_response.status if test_response else 'N/A'}). Re-running setup.")
                should_run_setup = True
                await api_context.dispose()
            else:
                print("Existing session is valid.")
        if should_run_setup:
            assert REVIEW_ID is not None
            await perform_full_setup(p, REVIEW_ID)
            with open(HEADERS_FILE, "r") as f:
                headers = json.load(f)
            api_context = await p.request.new_context(storage_state=AUTH_FILE, extra_http_headers=headers)

        # --- Phase 2: Main Processing Loop ---
        assert api_context is not None, "API context should have been initialized."
        start_index = 0
        batch_size = 50 # Reduced batch size to be gentler on APIs
        while True:
            assert REVIEW_ID is not None
            response_obj = await fetch_undecided_articles(api_context, REVIEW_ID, start_index, batch_size)
            if not response_obj or not response_obj.ok:
                 print(f"Failed to fetch articles. Status: {response_obj.status if response_obj else 'N/A'}. Stopping.")
                 break
            data = await response_obj.json()
            articles = data.get("data", [])
            if not articles:
                print("\nNo more undecided articles to process. All done!")
                break
            print(f"\n--- Fetched batch of {len(articles)} articles (Total processed: {start_index}) ---")

            for article in articles:
                article_id = article.get('id')
                title = article.get('title', 'No Title')
                print(f"\nProcessing Article ID: {article_id} - '{title[:70]}...'")

                # 1. Get AI Decision
                ai_result = await get_ai_decision(article)

                # 2. Safely extract decision and reason
                decision = ai_result.get("decision", "maybe") # Default to 'maybe' if AI fails
                reason = ai_result.get("reason")

                # 3. Update the status in Rayyan
                await update_article_status(api_context, REVIEW_ID, article_id, decision, reason)

                # 4. Be a good API citizen to avoid rate limiting
                await asyncio.sleep(6) # 60 seconds / 10 requests = 6s delay per request

            start_index += len(articles)

        if api_context:
            await api_context.dispose()
        print("\nScript finished.")

if __name__ == "__main__":
    asyncio.run(main())
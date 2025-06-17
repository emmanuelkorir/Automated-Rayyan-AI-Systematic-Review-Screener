# Automated Rayyan-AI Systematic Review Screener

[Rayyan-AI](https://rayyan.ai/) is a tool for screening articles in systematic reviews using AI (Google Gemini) and the Rayyan platform. It helps researchers efficiently include or exclude articles based on strict PICO criteria, reducing manual workload and improving reproducibility.

## What does this project do?

- Automates the screening of articles for systematic reviews on Rayyan.
- Uses Google Gemini AI to decide inclusion/exclusion based on your protocol.
- Updates article status in Rayyan automatically.
- Designed for medical research, especially meta-analyses and systematic reviews.

## Who is it for?

- Researchers conducting systematic reviews and meta-analyses.
- Anyone using Rayyan for literature screening.
- Teams looking to speed up and standardize article selection.

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/yourusername/rayyan-ai.git
cd rayyan-ai
pip install -r requirements.txt
```

## Configuration

1. Create a `.env` file in the project root with the following variables:

   ```
   GEMINI_API_KEY=your_google_gemini_api_key
   RAYYAN_EMAIL=your_rayyan_email
   RAYYAN_PASSWORD=your_rayyan_password
   REVIEW_ID=your_rayyan_review_id
   ```

2. Make sure you have access to the Rayyan review you want to screen.

## Usage

Run the main script:

```bash
python main.py
```

- The script will guide you through authentication and setup if needed.
- It will fetch undecided articles, use Gemini AI to screen them, and update their status in Rayyan.

## Python Requirements

See [requirements.txt](requirements.txt) for all dependencies.

To install:

```bash
pip install -r requirements.txt
```

## API Reference

The script interacts with the Rayyan API to fetch and update article statuses. It also uses Google Gemini for AI-powered screening.

## Features

- Automated article screening using AI
- Strict adherence to PICO and inclusion/exclusion criteria
- Seamless integration with Rayyan
- Batch processing with rate limiting
- Easy configuration via `.env` file

## Tech Stack

**Client:** Playwright (for browser automation)  
**AI:** Google Gemini SDK
**Server:** Python (asyncio, requests)

## Authors

- [@emmanuelkorir](https://www.github.com/emmanuelkorir)

## License

MIT

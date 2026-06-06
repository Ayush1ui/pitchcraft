# Pitchcraft

An interactive web app that turns a product into ready-to-post marketing copy —
caption, hashtags, and a visual idea — for Instagram, Facebook, and LinkedIn.
The whole tool lives in a single file: app.py.

## Works out of the box
- No setup required. With no API key, a built-in generator writes real copy offline, for free.
- Optional AI upgrade. Add an Anthropic API key and it automatically switches to AI-written copy.

## Run it
You need Python 3 installed (from https://python.org — on Windows, tick "Add python.exe to PATH").

In a terminal opened inside this folder:

    python -m venv venv
    venv\Scripts\activate
    pip install flask anthropic python-dotenv
    python app.py

Then open http://127.0.0.1:5000 in your browser. Stop the server with Ctrl+C.

## Optional: turn on AI copy
Create a file named .env next to app.py containing a key from https://console.anthropic.com:

    ANTHROPIC_API_KEY=sk-ant-...

Restart the app. Nothing else changes.

## Posting for real (the safe, legal path)
This tool drafts copy. To publish, use the official APIs on accounts you own:
Meta Graph API for Instagram/Facebook, LinkedIn Share API for LinkedIn. It does
not create fake accounts or auto-comment on others' posts.

## License
MIT

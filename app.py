r"""
Pitchcraft — a complete AI marketing tool in ONE file.

HOW TO RUN (no editing needed):
    python -m venv venv
    # Windows: venv\Scripts\activate   |   Mac/Linux: source venv/bin/activate
    pip install flask anthropic python-dotenv
    python app.py
Then open http://127.0.0.1:5000

Works with NO API key (uses a built-in generator). If you ever want AI-written
copy, create a file named ".env" next to this one containing:
    ANTHROPIC_API_KEY=sk-ant-your-key
...and restart. Nothing else changes.

This drafts copy for YOUR OWN accounts. Publish via the official platform APIs.
It does not create fake accounts or auto-comment on others' posts.
"""

import os
import re
import json

from flask import Flask, request, jsonify, render_template_string

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass  # dotenv is optional

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
app = Flask(__name__)

PLATFORM_GUIDES = {
    "instagram": "Casual, visual, emoji-friendly. Hook then 1-3 short sentences. 8-12 hashtags.",
    "facebook":  "Conversational. Relatable hook, the benefit, a clear call to action. 1-3 hashtags.",
    "linkedin":  "Professional, value-led. Insight or problem, then how it helps. 3-5 niche hashtags.",
}

STOPWORDS = set((
    "a an the and or but with for from of to in on at by is are be it this that "
    "your you our we they made make using uses use plus more most best new now "
    "get gets buy buys has have will can also so very really just like into out"
).split())

TONE = {
    "friendly":     ("Say hello to {p} \U0001F44B", "A friendly little upgrade your day's been missing."),
    "bold":         ("{p}. No compromises.", "Built for people who refuse to settle."),
    "playful":      ("Okay, {p} is kind of a big deal \U0001F92D", "Don't say we didn't warn you."),
    "professional": ("Introducing {p}.", "Thoughtfully made to do exactly what you need."),
    "luxurious":    ("{p} \u2014 refined to the last detail.", "For those who appreciate the finer things."),
}
IDEAS = {
    "instagram": "A bright close-up of {p} in natural light against a clean, simple background.",
    "facebook":  "A short clip of {p} in everyday use, with on-screen text of the main benefit.",
    "linkedin":  "A clean product photo of {p} paired with a one-line customer quote or stat.",
}
EXTRA_TAGS = {"instagram": ["#instagood", "#shopsmall", "#musthave"],
              "facebook": ["#smallbusiness"], "linkedin": ["#innovation", "#business"]}
TAG_LIMIT = {"instagram": 10, "facebook": 3, "linkedin": 5}


def _keywords(text, limit=6):
    out = []
    for w in re.findall(r"[A-Za-z]+", text.lower()):
        if len(w) > 2 and w not in STOPWORDS and w not in out:
            out.append(w)
    return out[:limit]


def _hashtags(product, description, platform):
    tags = []
    brand = "".join(w.capitalize() for w in re.findall(r"[A-Za-z]+", product)[:3])
    if brand:
        tags.append("#" + brand)
    tags += ["#" + w.capitalize() for w in _keywords(product + " " + description)]
    tags += EXTRA_TAGS.get(platform, [])
    seen = []
    for t in tags:
        if len(t) > 1 and t.lower() not in [x.lower() for x in seen]:
            seen.append(t)
    return seen[: TAG_LIMIT.get(platform, 8)]


def _caption(product, description, platform, tone):
    hook, closer = TONE.get(tone, TONE["friendly"])
    body = f"{hook.format(p=product)}\n\n{description.rstrip('. ').strip()}. {closer}"
    if platform == "facebook":
        body += "\n\n\U0001F449 Tap to learn more."
    elif platform == "linkedin":
        body += "\n\nWe'd love to hear what you think."
    return body


def template_generate(product, description, platform, tone):
    return {
        "caption": _caption(product, description, platform, tone),
        "hashtags": _hashtags(product, description, platform),
        "post_idea": IDEAS.get(platform, IDEAS["instagram"]).format(p=product),
    }


def ai_generate(product, description, platform, tone, key):
    from anthropic import Anthropic
    client = Anthropic(api_key=key)
    prompt = f"""You are an expert marketing copywriter. Write a {tone} marketing post.

Product: {product}
Description: {description}
Platform: {platform}
Platform style: {PLATFORM_GUIDES[platform]}

Respond ONLY with valid JSON (no markdown, no backticks) in this exact shape:
{{"caption": "...", "hashtags": ["#a", "#b"], "post_idea": "..."}}"""
    resp = client.messages.create(model=MODEL, max_tokens=1000,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def generate_post(product, description, platform, tone):
    platform = platform.lower()
    if platform not in PLATFORM_GUIDES:
        raise ValueError("Unknown platform")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key and key != "your-key-here":
        try:
            post = ai_generate(product, description, platform, tone, key)
            post["engine"] = "AI"
            return post
        except Exception:
            pass
    post = template_generate(product, description, platform, tone)
    post["engine"] = "Built-in"
    return post


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pitchcraft</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,900;1,9..144,500&family=Spline+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--ink:#1b1714;--paper:#f4ece0;--card:#fffaf2;--accent:#e8542a;--accent-soft:#f6c9b6;--muted:#8a7d6e;--line:#e0d4c2;--shadow:24px 24px 0 rgba(27,23,20,.06)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Spline Sans",sans-serif;background:var(--paper);color:var(--ink);min-height:100vh;line-height:1.5;overflow-x:hidden}
.masthead{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:28px 6vw 0}
.logo{font-family:"Fraunces",serif;font-weight:900;font-size:28px;letter-spacing:-.02em}.logo .dot{color:var(--accent)}
.kicker{font-size:13px;text-transform:uppercase;letter-spacing:.18em;color:var(--muted)}
.layout{display:grid;grid-template-columns:1.05fr 1fr;gap:32px;padding:40px 6vw 60px;align-items:start}
@media(max-width:860px){.layout{grid-template-columns:1fr}}
.panel{background:var(--card);border:1.5px solid var(--ink);border-radius:4px;box-shadow:var(--shadow);padding:36px}
.headline{font-family:"Fraunces",serif;font-weight:900;font-size:clamp(34px,4.5vw,54px);line-height:.98;letter-spacing:-.02em;margin-bottom:18px}
.headline em{font-style:italic;font-weight:500;color:var(--accent)}
.sub{color:var(--muted);margin-bottom:28px;max-width:46ch}
.field{margin-bottom:18px;display:flex;flex-direction:column}.field-row{display:flex;gap:16px}.field-row .field{flex:1}
label{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:7px}
input,textarea,select{font-family:inherit;font-size:16px;color:var(--ink);background:var(--paper);border:1.5px solid var(--line);border-radius:3px;padding:12px 14px;transition:border-color .15s,box-shadow .15s}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
textarea{resize:vertical}
.generate-btn{margin-top:8px;width:100%;display:inline-flex;align-items:center;justify-content:center;gap:10px;font-family:"Fraunces",serif;font-weight:600;font-size:18px;color:var(--card);background:var(--ink);border:none;border-radius:3px;padding:15px;cursor:pointer;transition:transform .1s,background .2s}
.generate-btn:hover{background:var(--accent)}.generate-btn:active{transform:translateY(2px)}.generate-btn:disabled{opacity:.6;cursor:progress}
.btn-spinner{width:16px;height:16px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;display:none;animation:spin .7s linear infinite}
.generate-btn.loading .btn-spinner{display:inline-block}@keyframes spin{to{transform:rotate(360deg)}}
.status{margin-top:12px;font-size:14px;min-height:20px}.status.error{color:var(--accent)}
.results-panel{min-height:320px}
.empty-state{height:100%;min-height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--muted);text-align:center;gap:14px}
.empty-mark{font-size:46px;color:var(--accent-soft)}
.results{display:flex;flex-direction:column;gap:18px}
.card{border:1.5px solid var(--line);border-radius:3px;padding:20px;background:var(--paper);animation:rise .45s cubic-bezier(.2,.8,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(14px)}}
.card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.platform-tag{font-family:"Fraunces",serif;font-weight:600;font-size:18px;text-transform:capitalize;flex:1}
.engine-badge{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:3px 9px;margin-right:10px}
.copy-btn{font-family:inherit;font-size:12px;letter-spacing:.06em;text-transform:uppercase;background:none;border:1.5px solid var(--ink);border-radius:2px;padding:6px 10px;cursor:pointer;transition:background .15s,color .15s}
.copy-btn:hover{background:var(--ink);color:var(--card)}.copy-btn.copied{background:var(--accent);border-color:var(--accent);color:#fff}
.caption{white-space:pre-wrap;margin-bottom:14px}
.hashtags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.chip{font-size:13px;color:var(--accent);background:var(--accent-soft);border-radius:999px;padding:3px 10px}
.idea{font-size:14px;color:var(--muted);border-top:1px dashed var(--line);padding-top:12px}.idea strong{color:var(--ink);font-weight:600}
.footer{text-align:center;padding:0 6vw 40px;color:var(--muted);font-size:13px}
</style></head><body>
<header class="masthead"><div class="logo">Pitchcraft<span class="dot">.</span></div>
<p class="kicker">AI marketing copy, built for your own channels</p></header>
<main class="layout">
<section class="panel">
<h1 class="headline">Turn a product into<br><em>posts that sell.</em></h1>
<p class="sub">Describe what you're selling. Pick a platform and a vibe. Get caption, hashtags, and a visual idea — instantly.</p>
<div class="field"><label for="product">Product name</label><input id="product" placeholder="e.g. Bamboo Toothbrush"></div>
<div class="field"><label for="description">What is it? (a sentence or two)</label>
<textarea id="description" rows="3" placeholder="Eco-friendly toothbrush, biodegradable handle, soft bristles"></textarea></div>
<div class="field-row">
<div class="field"><label for="platform">Platform</label><select id="platform">
<option value="all">All three</option><option value="instagram">Instagram</option>
<option value="facebook">Facebook</option><option value="linkedin">LinkedIn</option></select></div>
<div class="field"><label for="tone">Tone</label><select id="tone">
<option value="friendly">Friendly</option><option value="bold">Bold</option><option value="playful">Playful</option>
<option value="professional">Professional</option><option value="luxurious">Luxurious</option></select></div></div>
<button id="generate" class="generate-btn"><span class="btn-label">Generate copy</span><span class="btn-spinner"></span></button>
<p id="status" class="status"></p></section>
<section class="panel results-panel">
<div id="empty" class="empty-state"><div class="empty-mark">&#10042;</div><p>Your generated posts will appear here.</p></div>
<div id="results" class="results"></div></section></main>
<footer class="footer"><p>Generates copy for accounts you own. Publish through the official platform APIs.</p></footer>
<script>
const btn=document.getElementById("generate"),status=document.getElementById("status"),
resultsEl=document.getElementById("results"),emptyEl=document.getElementById("empty");
btn.addEventListener("click",generate);
async function generate(){
 const product=document.getElementById("product").value.trim(),
 description=document.getElementById("description").value.trim(),
 platform=document.getElementById("platform").value,tone=document.getElementById("tone").value;
 if(!product||!description){setStatus("Please fill in the product name and description.",true);return;}
 setLoading(true);setStatus("Writing your posts…");
 try{
  const res=await fetch("/api/generate",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({product,description,platform,tone})});
  const data=await res.json();
  if(!res.ok)throw new Error(data.error||"Something went wrong.");
  render(data.results);setStatus("Done. Edit anything before you post it.");
 }catch(e){setStatus(e.message,true);}finally{setLoading(false);}
}
function render(results){
 emptyEl.style.display="none";resultsEl.innerHTML="";
 Object.entries(results).forEach(([platform,post],i)=>{
  const card=document.createElement("div");card.className="card";card.style.animationDelay=(i*0.08)+"s";
  const hashtags=(post.hashtags||[]).map(h=>'<span class="chip">'+esc(h)+'</span>').join("");
  const fullText=post.caption+"\n\n"+(post.hashtags||[]).join(" ");
  card.innerHTML='<div class="card-head"><span class="platform-tag">'+esc(platform)+
   '</span><span class="engine-badge">'+esc(post.engine||"")+'</span><button class="copy-btn">Copy</button></div>'+
   '<p class="caption">'+esc(post.caption||"")+'</p><div class="hashtags">'+hashtags+
   '</div><p class="idea"><strong>Visual idea:</strong> '+esc(post.post_idea||"")+'</p>';
  const cb=card.querySelector(".copy-btn");
  cb.addEventListener("click",()=>{navigator.clipboard.writeText(fullText);
   cb.textContent="Copied!";cb.classList.add("copied");
   setTimeout(()=>{cb.textContent="Copy";cb.classList.remove("copied");},1500);});
  resultsEl.appendChild(card);
 });
}
function setLoading(b){btn.disabled=b;btn.classList.toggle("loading",b);
 btn.querySelector(".btn-label").textContent=b?"Generating…":"Generate copy";}
function setStatus(m,e=false){status.textContent=m;status.classList.toggle("error",e);}
function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
</script></body></html>"""


@app.route("/")
def home():
    return render_template_string(PAGE)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}
    product = (data.get("product") or "").strip()
    description = (data.get("description") or "").strip()
    platform = (data.get("platform") or "all").strip().lower()
    tone = (data.get("tone") or "friendly").strip()
    if not product or not description:
        return jsonify({"error": "Please enter a product name and description."}), 400
    platforms = list(PLATFORM_GUIDES) if platform == "all" else [platform]
    results = {p: generate_post(product, description, p, tone) for p in platforms}
    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

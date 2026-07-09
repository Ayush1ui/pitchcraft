import os
import re
import json
import html
import base64
import urllib.request
import urllib.parse

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
    "x":         "Very short and punchy. One strong hook, ~240 characters max, 1-2 hashtags.",
    "reddit":    "Authentic and non-promotional. A clear title and an honest, helpful body. No hashtags, no hype.",
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
    "creative":     ("Reimagine your day with {p}.", "Made for people who see things a little differently."),
    "official":     ("Presenting {p}.", "Engineered to deliver, every single time."),
    "classic":      ("{p} \u2014 timeless by design.", "Quality that never goes out of style."),
}
IDEAS = {
    "instagram": "A bright close-up of {p} in natural light against a clean, simple background.",
    "facebook":  "A short clip of {p} in everyday use, with on-screen text of the main benefit.",
    "linkedin":  "A clean product photo of {p} paired with a one-line customer quote or stat.",
    "x":         "A crisp product shot or a 2-3 second looping clip that reads fast in the feed.",
    "reddit":    "An honest, well-lit photo of {p} in real use \u2014 Reddit values authenticity over polish.",
}
EXTRA_TAGS = {"instagram": ["#instagood", "#shopsmall", "#musthave"],
              "facebook": ["#smallbusiness"], "linkedin": ["#innovation", "#business"],
              "x": [], "reddit": []}
TAG_LIMIT = {"instagram": 10, "facebook": 3, "linkedin": 5, "x": 2, "reddit": 0}


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
    hook = hook.format(p=product)
    desc = description.rstrip(". ").strip()
    if platform == "x":  # short and punchy for a fast feed
        s = f"{hook} {desc}."
        return (s[:236] + "\u2026") if len(s) > 238 else s
    if platform == "reddit":  # authentic title + honest body, no hype/hashtags
        return f"{product}\n\n{desc}."
    body = f"{hook}\n\n{desc}. {closer}"
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


# ----- Fetch product details from a URL (title, description, image). -----
# Uses only the standard library. Optionally routes through a fetching service
# (ScraperAPI-compatible) so blocked sites like Amazon/Flipkart work at scale:
# set SCRAPER_API_KEY in your environment to turn that on.

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SCRAPER_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()


def _open(url, timeout=None):
    """Open a URL directly, or through the fetching service if a key is set."""
    target = url
    if SCRAPER_KEY:
        target = "https://api.scraperapi.com/?" + urllib.parse.urlencode(
            {"api_key": SCRAPER_KEY, "url": url, "render": "true"})
        timeout = timeout or 70  # rendered fetches take longer
    req = urllib.request.Request(target, headers={
        "User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"})
    return urllib.request.urlopen(req, timeout=timeout or 15)


def _meta_tags(page_html):
    """Return a dict of <meta property/name> -> content."""
    tags = {}
    for tag in re.findall(r"<meta\s+[^>]+>", page_html, re.I):
        key = re.search(r'(?:property|name)\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        val = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        if key and val:
            tags.setdefault(key.group(1).lower(), html.unescape(val.group(1)).strip())
    return tags


def _find_image_in_jsonld(data):
    """Recursively pull the first image URL out of schema.org JSON-LD data."""
    if isinstance(data, list):
        for d in data:
            r = _find_image_in_jsonld(d)
            if r:
                return r
        return ""
    if isinstance(data, dict):
        if data.get("@graph"):
            r = _find_image_in_jsonld(data["@graph"])
            if r:
                return r
        img = data.get("image")
        if isinstance(img, str):
            return img
        if isinstance(img, dict):
            return img.get("url") or img.get("@id") or ""
        if isinstance(img, list) and img:
            first = img[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                return first.get("url") or first.get("@id") or ""
    return ""


def _jsonld_data(page_html):
    """Return all parsed JSON-LD blocks from the page."""
    out = []
    for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            page_html, re.I | re.S):
        try:
            out.append(json.loads(block.strip()))
        except Exception:
            continue
    return out


def _find_field(data, field):
    """Return the first string value of `field` from JSON-LD, preferring
    schema.org Product nodes (cleaner than a page's <title>)."""
    def walk(d, require_product):
        if isinstance(d, list):
            for x in d:
                r = walk(x, require_product)
                if r:
                    return r
            return ""
        if isinstance(d, dict):
            if d.get("@graph"):
                r = walk(d["@graph"], require_product)
                if r:
                    return r
            t = d.get("@type", "")
            is_prod = ("Product" in t) if isinstance(t, str) else ("Product" in (t or []))
            if (not require_product) or is_prod:
                v = d.get(field)
                if isinstance(v, str) and v.strip():
                    return html.unescape(v.strip())
            for v in d.values():
                if isinstance(v, (list, dict)):
                    r = walk(v, require_product)
                    if r:
                        return r
        return ""
    return walk(data, True) or walk(data, False)


def _amazon_image(page_html):
    """Amazon hides the main product image in JS/data attributes, not og tags."""
    # data-a-dynamic-image='{"https://...jpg":[w,h], ...}' -> pick largest
    m = re.search(r'data-a-dynamic-image\s*=\s*["\'](\{.*?\})["\']', page_html, re.I | re.S)
    if m:
        try:
            d = json.loads(html.unescape(m.group(1)))
            if d:
                best = max(d.items(), key=lambda kv: (kv[1][0] * kv[1][1])
                           if isinstance(kv[1], list) and len(kv[1]) >= 2 else 0)
                return best[0]
        except Exception:
            pass
    for pat in (r'data-old-hires\s*=\s*["\'](https://[^"\']+)["\']',
                r'"hiRes"\s*:\s*"(https://[^"]+?)"',
                r'"large"\s*:\s*"(https://[^"]+?\.jpg)"',
                r'id=["\']landingImage["\'][^>]*\ssrc=["\'](https://[^"\']+)["\']'):
        m = re.search(pat, page_html, re.I)
        if m:
            return m.group(1).replace("\\/", "/")
    return ""


def parse_product(page_html, base_url):
    """Pull product name, description, and image URL out of page HTML,
    checking Open Graph tags, then embedded JSON-LD product data."""
    m = _meta_tags(page_html)
    ld = _jsonld_data(page_html)
    title = m.get("og:title") or m.get("twitter:title") or ""
    desc = (m.get("og:description") or m.get("description")
            or m.get("twitter:description") or "")
    img = (m.get("og:image") or m.get("og:image:secure_url")
           or m.get("twitter:image") or "")

    # JSON-LD gives the cleanest product data on many stores (incl. some Amazon).
    for data in ld:
        if not title:
            title = _find_field(data, "name")
        if not desc:
            desc = _find_field(data, "description")
        if not img:
            img = _find_image_in_jsonld(data)

    if not img:  # Amazon and some others hide the image in JS/data attributes
        img = _amazon_image(page_html)
    if not title:  # last resort: the page <title>
        t = re.search(r"<title[^>]*>([^<]+)</title>", page_html, re.I)
        title = html.unescape(t.group(1)).strip() if t else ""
    if not img:
        l = re.search(r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)',
                      page_html, re.I)
        if l:
            img = l.group(1)

    if img:
        img = urllib.parse.urljoin(base_url, html.unescape(img))
    return {"product": title[:120], "description": desc[:400], "image_url": img}


def _fetch_image_data(img_url):
    """Download an image and return it as a base64 data URL (so the browser
    can draw it onto a canvas without cross-origin problems). Image CDNs are
    usually not blocked, so this is fetched directly."""
    try:
        req = urllib.request.Request(img_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0]
            if "image" not in ctype:
                return ""
            data = resp.read(5_000_000)  # cap at ~5MB
        return "data:%s;base64,%s" % (ctype, base64.b64encode(data).decode("ascii"))
    except Exception:
        return ""


def fetch_product(url):
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    with _open(url) as resp:
        raw = resp.read(2_500_000)  # cap at ~2.5MB of HTML
    page_html = raw.decode("utf-8", "ignore")
    info = parse_product(page_html, url)
    img_url = info.pop("image_url", "")
    info["image"] = _fetch_image_data(img_url) if img_url else ""
    info["diag"] = {"via": "scraper" if SCRAPER_KEY else "direct",
                    "kb": round(len(page_html) / 1024),
                    "img_url_found": bool(img_url),
                    "img_loaded": bool(info["image"])}
    return info


def _strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _get_direct(url, cap):
    """Plain direct fetch (used for Shopify's open JSON feed — never blocked)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read(cap)


def parse_shopify(data):
    """Turn a Shopify /products.json payload into our product list shape."""
    out = []
    for p in data.get("products", []):
        imgs = p.get("images") or []
        src = imgs[0].get("src") if imgs and isinstance(imgs[0], dict) else ""
        out.append({"name": (p.get("title") or "")[:120],
                    "description": _strip_html(p.get("body_html"))[:400],
                    "image": src or ""})
    return out


def _collect_products_jsonld(data, out, base):
    """Best-effort: pull Product entries out of a page's JSON-LD (non-Shopify)."""
    if isinstance(data, list):
        for d in data:
            _collect_products_jsonld(d, out, base)
        return
    if not isinstance(data, dict):
        return
    if data.get("@graph"):
        _collect_products_jsonld(data["@graph"], out, base)
    t = data.get("@type", "")
    is_prod = ("Product" in t) if isinstance(t, str) else ("Product" in (t or []))
    if is_prod and data.get("name"):
        img = _find_image_in_jsonld(data)
        out.append({"name": str(data["name"])[:120],
                    "description": _strip_html(data.get("description", ""))[:400],
                    "image": urllib.parse.urljoin(base, img) if img else ""})
    for el in (data.get("itemListElement") or []):
        item = el.get("item") if isinstance(el, dict) else None
        if isinstance(item, dict):
            _collect_products_jsonld(item, out, base)


def fetch_products(url):
    """List a store's products. Tries Shopify's feed first, then page JSON-LD."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urllib.parse.urlparse(url)
    origin = parts.scheme + "://" + parts.netloc
    try:  # 1) Shopify open product feed (reliable)
        raw = _get_direct(origin + "/products.json?limit=250", 3_000_000)
        prods = parse_shopify(json.loads(raw.decode("utf-8", "ignore")))
        if prods:
            return {"products": prods[:100], "source": "shopify"}
    except Exception:
        pass
    try:  # 2) best-effort: Product data embedded in the page
        with _open(url) as resp:
            page = resp.read(2_500_000).decode("utf-8", "ignore")
        col = []
        for d in _jsonld_data(page):
            _collect_products_jsonld(d, col, url)
        if col:
            return {"products": col[:60], "source": "jsonld"}
    except Exception:
        pass
    return {"products": [], "source": "none"}


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pitchcraft</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,900;1,9..144,500&family=Spline+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--ink:#1b1714;--paper:#f4ece0;--card:#fffaf2;--accent:#e8542a;--accent-soft:#f6c9b6;--muted:#8a7d6e;--line:#e0d4c2;--shadow:24px 24px 0 rgba(27,23,20,.06)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Spline Sans",sans-serif;background:var(--paper);color:var(--ink);min-height:100vh;line-height:1.5}
.masthead{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:26px 6vw 0}
.logo{font-family:"Fraunces",serif;font-weight:900;font-size:28px;letter-spacing:-.02em}.logo .dot{color:var(--accent)}
.kicker{font-size:13px;text-transform:uppercase;letter-spacing:.18em;color:var(--muted)}
.wrap{max-width:940px;margin:0 auto;padding:30px 6vw 60px}
.steps{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:24px}
.stepdot{display:flex;align-items:center;gap:8px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);opacity:.45}
.stepdot .num{width:26px;height:26px;border-radius:50%;border:1.5px solid var(--muted);display:flex;align-items:center;justify-content:center;font-family:"Fraunces",serif;font-weight:600;font-size:13px}
.stepdot.active{opacity:1;color:var(--ink)}.stepdot.active .num{border-color:var(--accent);background:var(--accent);color:#fff}
.stepdot.done{opacity:1;color:var(--ink)}.stepdot.done .num{border-color:var(--ink);background:var(--ink);color:#fff}
.panel{background:var(--card);border:1.5px solid var(--ink);border-radius:4px;box-shadow:var(--shadow);padding:34px}
.step{display:none}.step.active{display:block}
h2.title{font-family:"Fraunces",serif;font-weight:900;font-size:clamp(26px,3.4vw,40px);line-height:1.02;letter-spacing:-.02em;margin-bottom:8px}
.sub{color:var(--muted);margin-bottom:22px;max-width:60ch}
label{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:7px}
input,textarea,select{width:100%;font-family:inherit;font-size:16px;color:var(--ink);background:var(--paper);border:1.5px solid var(--line);border-radius:3px;padding:12px 14px}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
textarea{resize:vertical}
.row{display:flex;gap:10px}.row input{flex:1}
.btn{font-family:"Fraunces",serif;font-weight:600;font-size:17px;color:var(--card);background:var(--ink);border:none;border-radius:3px;padding:13px 22px;cursor:pointer;transition:background .2s}
.btn:hover{background:var(--accent)}.btn:disabled{opacity:.6;cursor:progress}
.btn-ghost{background:none;color:var(--ink);border:1.5px solid var(--ink)}
.btn-ghost:hover{background:var(--ink);color:var(--card)}
.nav{display:flex;justify-content:space-between;margin-top:26px;gap:12px;flex-wrap:wrap}
.note{font-size:13px;color:var(--muted);margin-top:12px}.note.error{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;max-height:460px;overflow-y:auto;padding:4px}
.pcard{border:1.5px solid var(--line);border-radius:4px;padding:10px;cursor:pointer;background:var(--paper);transition:border-color .15s,transform .1s;text-align:center}
.pcard:hover{border-color:var(--accent);transform:translateY(-2px)}
.pcard.sel{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.pcard img{width:100%;height:120px;object-fit:contain;background:#fff;border-radius:3px;margin-bottom:8px}
.pcard .pn{font-size:13px;font-weight:600;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.opts{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:12px}
.opt{border:1.5px solid var(--line);border-radius:4px;padding:16px;cursor:pointer;transition:border-color .15s;background:var(--paper)}
.opt:hover{border-color:var(--accent)}.opt.sel{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.opt .on{font-family:"Fraunces",serif;font-weight:600;font-size:17px}.opt .od{font-size:12px;color:var(--muted);margin-top:4px}
.result{border:1.5px solid var(--line);border-radius:3px;padding:20px;background:var(--paper);margin-bottom:18px}
.rhead{font-family:"Fraunces",serif;font-weight:600;font-size:18px;text-transform:capitalize;margin-bottom:10px}
.caption{white-space:pre-wrap;margin-bottom:12px}
.hashtags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.chip{font-size:13px;color:var(--accent);background:var(--accent-soft);border-radius:999px;padding:3px 10px}
.visual{margin-top:14px}
.carousel{display:flex;gap:12px;overflow-x:auto;padding-bottom:8px}
.slide{flex:0 0 auto;display:flex;flex-direction:column;gap:6px;align-items:center}
.slide img{width:150px;height:auto;max-height:260px;border:1.5px solid var(--line);border-radius:3px}
.single img{max-width:280px;border:1.5px solid var(--line);border-radius:3px;display:block;margin-bottom:8px}
.dl{font-family:inherit;font-size:12px;text-transform:uppercase;letter-spacing:.05em;background:none;border:1.5px solid var(--ink);border-radius:2px;padding:5px 10px;cursor:pointer;text-decoration:none;color:var(--ink);display:inline-block}
.dl:hover{background:var(--ink);color:var(--card)}
.copybtn{float:right;font-size:12px;text-transform:uppercase;letter-spacing:.05em;background:none;border:1.5px solid var(--ink);border-radius:2px;padding:5px 10px;cursor:pointer}
.copybtn:hover{background:var(--ink);color:var(--card)}
.uploads{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.uploads img{height:64px;width:64px;object-fit:cover;border:1.5px solid var(--line);border-radius:3px}
</style></head><body>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.js"></script>
<header class="masthead"><div class="logo">Pitchcraft<span class="dot">.</span></div>
<p class="kicker">Store URL to social posts</p></header>
<div class="wrap">
 <div class="steps" id="steps"></div>
 <div class="panel">

  <div class="step active" id="s1">
   <h2 class="title">Start with your store</h2>
   <p class="sub">Paste your store's web address and we'll pull in its products. Works best on Shopify stores. No store link? You can enter a product by hand.</p>
   <label for="store">Store URL</label>
   <div class="row"><input id="store" placeholder="https://yourstore.com"><button class="btn" id="findbtn">Find products</button></div>
   <p class="note" id="findnote"></p>
   <div class="nav"><span></span><button class="btn btn-ghost" id="manualbtn">Enter a product manually instead</button></div>
  </div>

  <div class="step" id="s2">
   <h2 class="title">Pick a product</h2>
   <p class="sub" id="s2sub">Choose the product you want to advertise.</p>
   <div class="grid" id="prodgrid"></div>
   <div id="manualbox" style="display:none">
    <label for="pname">Product name</label><input id="pname" placeholder="e.g. Bamboo Toothbrush">
    <label for="pdesc" style="margin-top:14px">What is it?</label><textarea id="pdesc" rows="3" placeholder="A sentence or two about the product"></textarea>
    <label for="upload" style="margin-top:14px">Product image (optional, for real photos)</label>
    <input id="upload" type="file" accept="image/*"><div class="uploads" id="uploads"></div>
   </div>
   <div class="nav"><button class="btn btn-ghost" onclick="goto(1)">Back</button><button class="btn" id="s2next">Next</button></div>
  </div>

  <div class="step" id="s3">
   <h2 class="title">Choose the platform</h2>
   <p class="sub">Where is this going? Pick one, or all five at once.</p>
   <div class="opts" id="platopts"></div>
   <div class="nav"><button class="btn btn-ghost" onclick="goto(2)">Back</button><button class="btn" onclick="goto(4)">Next</button></div>
  </div>

  <div class="step" id="s4">
   <h2 class="title">Choose the idea / tone</h2>
   <p class="sub">How should it sound?</p>
   <div class="opts" id="toneopts"></div>
   <div class="nav"><button class="btn btn-ghost" onclick="goto(3)">Back</button><button class="btn" onclick="goto(5)">Next</button></div>
  </div>

  <div class="step" id="s5">
   <h2 class="title">Choose the content type</h2>
   <p class="sub">What visual do you want with the copy?</p>
   <div class="opts" id="typeopts"></div>
   <label for="imgsize" style="margin-top:18px">Size</label>
   <select id="imgsize"><option value="square">Square &mdash; 1080&times;1080 (feed)</option><option value="portrait">Portrait &mdash; 1080&times;1350 (feed, taller)</option><option value="story">Story / Reel &mdash; 1080&times;1920 (vertical)</option></select>
   <div class="nav"><button class="btn btn-ghost" onclick="goto(4)">Back</button><button class="btn" id="genbtn">Generate</button></div>
  </div>

  <div class="step" id="s6">
   <h2 class="title">Your posts</h2>
   <p class="sub">Copy the text, download the visuals, and post to your own accounts.</p>
   <div id="output"></div>
   <div class="nav"><button class="btn btn-ghost" onclick="goto(5)">Back</button><button class="btn btn-ghost" onclick="goto(1)">Start over</button></div>
   <p class="note">Publishing straight to Instagram &amp; Facebook is the next phase. Reddit and X get content here but aren't auto-posted.</p>
  </div>

 </div>
</div>
<script>
const STEPS=["Store","Product","Platform","Idea","Type","Output"];
const PLATFORMS=[["all","All five","IG, FB, LinkedIn, X, Reddit"],["instagram","Instagram","Visual, hashtags"],["facebook","Facebook","Conversational"],["linkedin","LinkedIn","Professional"],["x","X (Twitter)","Short & punchy"],["reddit","Reddit","Authentic, no hype"]];
const TONES=[["friendly","Friendly",""],["bold","Bold",""],["playful","Playful",""],["creative","Creative",""],["official","Official",""],["classic","Classic","Old style"],["professional","Professional",""],["luxurious","Luxurious",""]];
const TYPES=[["image","Image","One branded graphic"],["carousel","Carousel","Multi-slide set"],["gif","GIF","Short animation"]];
const state={product:null,image:null,platform:"all",tone:"friendly",type:"image"};
let uploadedImg=null,cur=1;

function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function renderSteps(){const el=document.getElementById("steps");el.innerHTML="";
 STEPS.forEach((s,i)=>{const n=i+1;const d=document.createElement("div");
  d.className="stepdot"+(n===cur?" active":"")+(n<cur?" done":"");
  d.innerHTML='<span class="num">'+n+'</span>'+s;el.appendChild(d);});}
function goto(n){cur=n;document.querySelectorAll(".step").forEach(s=>s.classList.remove("active"));
 document.getElementById("s"+n).classList.add("active");renderSteps();window.scrollTo(0,0);}
function opt(container,items,key){const el=document.getElementById(container);el.innerHTML="";
 items.forEach(([val,name,desc])=>{const d=document.createElement("div");
  d.className="opt"+(state[key]===val?" sel":"");
  d.innerHTML='<div class="on">'+name+'</div>'+(desc?'<div class="od">'+desc+'</div>':'');
  d.addEventListener("click",()=>{state[key]=val;opt(container,items,key);});el.appendChild(d);});}
opt("platopts",PLATFORMS,"platform");opt("toneopts",TONES,"tone");opt("typeopts",TYPES,"type");renderSteps();

document.getElementById("findbtn").addEventListener("click",findProducts);
document.getElementById("manualbtn").addEventListener("click",()=>{
 document.getElementById("prodgrid").style.display="none";
 document.getElementById("manualbox").style.display="block";
 document.getElementById("s2sub").textContent="Enter the product details.";goto(2);});
async function findProducts(){
 const url=document.getElementById("store").value.trim(),note=document.getElementById("findnote");
 if(!url){note.textContent="Paste your store URL first.";note.className="note error";return;}
 note.textContent="Looking for products\u2026 this can take a few seconds.";note.className="note";
 const btn=document.getElementById("findbtn");btn.disabled=true;
 try{
  const res=await fetch("/api/products",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url})});
  const raw=await res.text();let data;
  try{data=JSON.parse(raw);}catch(e){note.textContent="The store took too long or blocked us. Enter the product manually.";note.className="note error";return;}
  const prods=data.products||[];
  if(!prods.length){note.textContent=data.error||"No products found.";note.className="note error";return;}
  renderProducts(prods);
  document.getElementById("prodgrid").style.display="grid";
  document.getElementById("manualbox").style.display="none";
  document.getElementById("s2sub").textContent="Found "+prods.length+" products. Pick the one to advertise.";goto(2);
 }catch(e){note.textContent="Couldn't reach the store: "+e.message;note.className="note error";}
 finally{btn.disabled=false;}}
function renderProducts(prods){const g=document.getElementById("prodgrid");g.innerHTML="";
 prods.forEach(p=>{const d=document.createElement("div");d.className="pcard";
  d.innerHTML=(p.image?'<img src="'+p.image+'" onerror="this.style.visibility=\'hidden\'">':'<div style="height:120px"></div>')+'<div class="pn">'+esc(p.name||"Product")+'</div>';
  d.addEventListener("click",async()=>{
   document.querySelectorAll(".pcard").forEach(c=>c.classList.remove("sel"));d.classList.add("sel");
   state.product={name:p.name,description:p.description};state.image=null;uploadedImg=null;
   if(p.image){try{const r=await fetch("/api/image",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:p.image})});const j=await r.json();if(j.image){const im=new Image();im.src=j.image;state.image=im;}}catch(e){}}});
  g.appendChild(d);});}
const uploadEl=document.getElementById("upload");
uploadEl.addEventListener("change",()=>{const box=document.getElementById("uploads");box.innerHTML="";uploadedImg=null;
 const f=uploadEl.files[0];if(f){const url=URL.createObjectURL(f);const im=new Image();im.src=url;uploadedImg=im;const t=document.createElement("img");t.src=url;box.appendChild(t);}});
document.getElementById("s2next").addEventListener("click",()=>{
 if(document.getElementById("manualbox").style.display!=="none"){
  const name=document.getElementById("pname").value.trim(),desc=document.getElementById("pdesc").value.trim();
  if(!name||!desc){alert("Please enter a product name and description.");return;}
  state.product={name,description};state.image=uploadedImg;
 }else{if(!state.product){alert("Pick a product first.");return;}}
 goto(3);});

document.getElementById("genbtn").addEventListener("click",generate);
async function generate(){const btn=document.getElementById("genbtn");btn.disabled=true;btn.textContent="Generating\u2026";
 try{
  const res=await fetch("/api/generate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({product:state.product.name,description:state.product.description,platform:state.platform,tone:state.tone})});
  const data=await res.json();
  if(data.error){alert(data.error);return;}
  await renderOutput(data.results);goto(6);
 }catch(e){alert("Error: "+e.message);}finally{btn.disabled=false;btn.textContent="Generate";}}
function activeImg(){return state.image||uploadedImg||null;}

async function renderOutput(results){const out=document.getElementById("output");out.innerHTML="";
 for(const key of Object.keys(results)){const post=results[key];
  const box=document.createElement("div");box.className="result";
  const tags=(post.hashtags||[]).map(h=>'<span class="chip">'+esc(h)+'</span>').join("");
  const full=post.caption+"\n\n"+(post.hashtags||[]).join(" ");
  box.innerHTML='<button class="copybtn">Copy</button><div class="rhead">'+esc(key)+'</div>'+
   '<p class="caption">'+esc(post.caption||"")+'</p><div class="hashtags">'+tags+'</div>'+
   '<p class="note">Visual idea: '+esc(post.post_idea||"")+'</p><div class="visual"></div>';
  box.querySelector(".copybtn").addEventListener("click",e=>{navigator.clipboard.writeText(full);e.target.textContent="Copied!";setTimeout(()=>e.target.textContent="Copy",1400);});
  out.appendChild(box);
  const vis=box.querySelector(".visual");
  if(state.type==="image")await makeImage(post,vis);
  else if(state.type==="carousel")await makeCarousel(post,vis);
  else await makeGif(post,vis);}}

function imgReady(im){return new Promise(r=>{if(!im||im.complete)return r();im.onload=()=>r();im.onerror=()=>r();});}
function imgSize(){const v=(document.getElementById("imgsize")||{}).value||"square";if(v==="portrait")return{w:1080,h:1350,tag:"portrait"};if(v==="story")return{w:1080,h:1920,tag:"story"};return{w:1080,h:1080,tag:"square"};}
function fname(p,s){return ((p||"post").replace(/\s+/g,"-").toLowerCase())+"-"+s;}
function wrapLines(ctx,text,maxW){const words=(text||"").split(" ");const out=[];let line="";for(const w of words){const t=line?line+" "+w:w;if(ctx.measureText(t).width>maxW&&line){out.push(line);line=w;}else line=t;}if(line)out.push(line);return out;}
function drawContain(x,img,dx,dy,dw,dh){const iw=img.naturalWidth,ih=img.naturalHeight;if(!iw||!ih)return;const s=Math.min(dw/iw,dh/ih),w=iw*s,h=ih*s,ox=dx+(dw-w)/2,oy=dy+(dh-h)/2;x.drawImage(img,ox,oy,w,h);}
function renderCard(o){const W=o.W,H=o.H,M=80,maxW=W-M*2;
 const c=document.createElement("canvas");c.width=W;c.height=H;const x=c.getContext("2d");x.textBaseline="alphabetic";
 x.fillStyle=o.bg;x.fillRect(0,0,W,H);
 const hasImg=o.image&&o.image.complete&&o.image.naturalWidth>0;
 x.fillStyle=o.muted;x.font='600 30px "Spline Sans",sans-serif';x.fillText((o.kicker||"").toUpperCase(),M,110);
 x.fillStyle=o.accent;x.fillRect(M,132,84,8);
 let areaTop=200;
 if(hasImg){const pt=170,pb=Math.round(H*0.58),ph=pb-pt,pad=34;
  x.fillStyle="#ffffff";x.fillRect(M,pt,W-2*M,ph);x.strokeStyle=o.line||"#e0d4c2";x.lineWidth=2;x.strokeRect(M,pt,W-2*M,ph);
  drawContain(x,o.image,M+pad,pt+pad,W-2*M-2*pad,ph-2*pad);areaTop=pb+46;}
 const showBody=!!o.body&&!hasImg;
 const tSize=hasImg?60:78,titleLH=hasImg?70:90,bSize=46,bodyLH=60,gap=42;
 const titleFont='900 '+tSize+'px "Fraunces",serif';
 const bodyFont=o.bodyItalic?'italic 500 '+bSize+'px "Fraunces",serif':'400 '+bSize+'px "Spline Sans",sans-serif';
 x.font=titleFont;const tl=wrapLines(x,o.title||"",maxW);
 let bl=[];if(showBody){x.font=bodyFont;bl=wrapLines(x,o.body,maxW);}
 const blockH=tl.length*titleLH+(bl.length?gap+bl.length*bodyLH:0);
 const areaBottom=H-150,area=areaBottom-areaTop;let y=areaTop+Math.max(0,(area-blockH)/2)+tSize*0.78;
 x.fillStyle=o.fg;x.font=titleFont;for(const ln of tl){x.fillText(ln,M,y);y+=titleLH;}
 if(bl.length){y+=gap;x.fillStyle=o.bodyColor||o.fg;x.font=bodyFont;for(const ln of bl){x.fillText(ln,M,y);y+=bodyLH;}}
 x.fillStyle=o.muted;x.font='500 30px "Spline Sans",sans-serif';x.fillText(o.footer||"PITCHCRAFT",M,H-90);
 return c;}

async function makeImage(post,host){await imgReady(activeImg());const s=imgSize();const hook=(post.caption||"").split("\n")[0];
 const c=renderCard({W:s.w,H:s.h,bg:"#f4ece0",fg:"#1b1714",accent:"#e8542a",muted:"#8a7d6e",line:"#e0d4c2",kicker:"Featured",title:state.product.name||"Your product",body:hook,bodyItalic:true,bodyColor:"#e8542a",image:activeImg(),footer:"PITCHCRAFT  \u2022  "+((post.hashtags||[]).slice(0,3).join("  "))});
 const wrap=document.createElement("div");wrap.className="single";const img=document.createElement("img");img.src=c.toDataURL("image/png");
 const a=document.createElement("a");a.href=img.src;a.download=fname(state.product.name,s.tag)+".png";a.textContent="Download image";a.className="dl";
 wrap.appendChild(img);wrap.appendChild(a);host.appendChild(wrap);}

async function makeCarousel(post,host){await imgReady(activeImg());const s=imgSize();const imgs=activeImg()?[activeImg()]:[];
 const hook=(post.caption||"").split("\n")[0],body=(post.caption||"").split("\n").slice(1).join(" ").trim(),tags=(post.hashtags||[]).slice(0,5).join("  "),desc=state.product.description;
 const photo={bg:"#f4ece0",fg:"#1b1714",accent:"#e8542a",muted:"#8a7d6e",line:"#e0d4c2"};
 const cta={bg:"#1b1714",fg:"#f4ece0",accent:"#e8542a",muted:"#a99e8e",kicker:"Get yours",title:"Tap the link in bio",body:tags,bodyColor:"#fffaf2"};
 let defs;
 if(imgs.length){defs=[Object.assign({},photo,{kicker:"New",title:state.product.name,image:imgs[0]}),{bg:"#f4ece0",fg:"#1b1714",accent:"#e8542a",muted:"#8a7d6e",kicker:"What it is",title:desc||hook},{bg:"#e8542a",fg:"#fffaf2",accent:"#fffaf2",muted:"#ffd9c8",kicker:"Why you'll love it",title:body||hook},cta];}
 else{defs=[{bg:"#1b1714",fg:"#f4ece0",accent:"#e8542a",muted:"#a99e8e",kicker:"New",title:state.product.name,body:hook,bodyItalic:true,bodyColor:"#e8542a"},{bg:"#f4ece0",fg:"#1b1714",accent:"#e8542a",muted:"#8a7d6e",kicker:"What it is",title:desc||hook},{bg:"#e8542a",fg:"#fffaf2",accent:"#fffaf2",muted:"#ffd9c8",kicker:"Why you'll love it",title:body||hook},cta];}
 const T=defs.length,strip=document.createElement("div");strip.className="carousel";
 defs.forEach((d,i)=>{d.W=s.w;d.H=s.h;d.footer="PITCHCRAFT  \u2022  "+(i+1)+"/"+T;const cv=renderCard(d);
  const b=document.createElement("div");b.className="slide";const im=document.createElement("img");im.src=cv.toDataURL("image/png");
  const a=document.createElement("a");a.href=im.src;a.download=fname(state.product.name,s.tag+"-slide-"+(i+1))+".png";a.textContent="Save "+(i+1);a.className="dl";
  b.appendChild(im);b.appendChild(a);strip.appendChild(b);});
 host.appendChild(strip);}

async function makeGif(post,host){
 if(typeof GIF==="undefined"){host.innerHTML='<p class="note error">GIF tool didn\'t load \u2014 check your connection and try again.</p>';return;}
 await imgReady(activeImg());const s=imgSize();const scale=Math.min(1,720/Math.max(s.w,s.h));const W=Math.round(s.w*scale),H=Math.round(s.h*scale);
 const hook=(post.caption||"").split("\n")[0],body=(post.caption||"").split("\n").slice(1).join(" ").trim(),tags=(post.hashtags||[]).slice(0,5).join("  "),img=activeImg();
 const frames=[{bg:"#1b1714",fg:"#f4ece0",accent:"#e8542a",muted:"#a99e8e",line:"#e0d4c2",kicker:"New",title:state.product.name,body:img?"":hook,bodyItalic:true,bodyColor:"#e8542a",image:img},{bg:"#f4ece0",fg:"#1b1714",accent:"#e8542a",muted:"#8a7d6e",kicker:"Why you'll love it",title:body||hook},{bg:"#e8542a",fg:"#fffaf2",accent:"#fffaf2",muted:"#ffd9c8",kicker:"Get yours",title:"Tap the link in bio",body:tags,bodyColor:"#fffaf2"}];
 host.innerHTML='<p class="note">Building GIF\u2026 a few seconds.</p>';
 let gif;try{gif=new GIF({workers:2,quality:10,width:W,height:H,workerScript:"https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.worker.js"});}catch(e){host.innerHTML='<p class="note error">Couldn\'t start the GIF tool.</p>';return;}
 frames.forEach(f=>{f.W=W;f.H=H;f.footer="PITCHCRAFT";gif.addFrame(renderCard(f),{delay:1400});});
 gif.on("finished",function(blob){const url=URL.createObjectURL(blob);host.innerHTML="";const im=document.createElement("img");im.src=url;im.style.maxWidth="260px";im.style.border="1.5px solid var(--line)";im.style.borderRadius="3px";im.style.display="block";im.style.marginBottom="8px";const a=document.createElement("a");a.href=url;a.download=fname(state.product.name,s.tag+"-animation")+".gif";a.textContent="Download GIF";a.className="dl";host.appendChild(im);host.appendChild(a);});
 gif.render();}
</script>
</body></html>"""


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


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Please paste a product URL."}), 400
    try:
        return jsonify(fetch_product(url))
    except Exception as e:
        return jsonify({"error": "Couldn't read that page — the site may block "
                        "automated access (Amazon often does). Fill the fields in "
                        "manually, or try a different product link."}), 200


@app.route("/api/products", methods=["POST"])
def api_products():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Please paste a store URL.", "products": []}), 400
    try:
        res = fetch_products(url)
    except Exception:
        return jsonify({"error": "Couldn't read that store. Try a product link, "
                        "or enter the product manually.", "products": []}), 200
    if not res.get("products"):
        return jsonify({"error": "Couldn't list products automatically (this works "
                        "best on Shopify stores). Enter the product manually, or "
                        "paste a single product link.", "products": []}), 200
    return jsonify(res)


@app.route("/api/image", methods=["POST"])
def api_image():
    data = request.get_json(silent=True) or {}
    u = (data.get("url") or "").strip()
    return jsonify({"image": _fetch_image_data(u) if u else ""})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

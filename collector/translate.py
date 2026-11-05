"""Machine translation of non-English postings into English.

Order of preference:
  1. DeepL, if a DEEPL_API_KEY secret is set (best quality; the free plan allows
     500,000 characters a month, far more than this tracker needs).
  2. Argos Translate models, run offline with CTranslate2 (free, no account).
     Models (~100 MB per language) are downloaded the first time a language is
     needed and kept in ~/.cache/mfj-translate (the workflow caches that folder).
  3. Nothing: the posting stays in its original language, unmarked.

Translations are cached by text in data/translations.json, so a posting is only
translated once.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import zipfile
from datetime import date
from pathlib import Path

import requests

from . import STATE_DIR

log = logging.getLogger(__name__)

CACHE_FILE = STATE_DIR / "translations.json"
MODEL_DIR = Path(os.environ.get("MFJ_MODEL_DIR", Path.home() / ".cache" / "mfj-translate"))
ARGOS_INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"

LANGUAGE_NAMES = {
    "ja": "Japanese", "zh": "Chinese", "zt": "Chinese", "ko": "Korean", "de": "German", "fr": "French",
    "es": "Spanish", "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "sv": "Swedish", "da": "Danish",
    "nb": "Norwegian", "fi": "Finnish", "pl": "Polish", "cs": "Czech", "tr": "Turkish", "ru": "Russian",
}

# ---------------------------------------------------------------- language detection
_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힯]")
_HAN = re.compile(r"[一-鿿]")
_EN_WORDS = {"the", "and", "of", "to", "in", "for", "with", "is", "are", "we", "our", "will", "on", "an",
             "be", "as", "at", "by", "this", "or", "from", "position", "applications", "university"}
_TRAD = re.compile(r"[們這學與無專時實發體對於應經認會區灣]")


def detect(text: str) -> str:
    """Two-letter language code ('en' when unsure)."""
    sample = (text or "")[:2000]
    if not sample.strip():
        return "en"
    letters = len(re.findall(r"\w", sample)) or 1
    if _KANA.search(sample):  # Chinese never uses kana
        return "ja"
    if len(_HANGUL.findall(sample)) / letters > 0.15:
        return "ko"
    han = len(_HAN.findall(sample))
    if han / letters > 0.2:
        return "zt" if len(_TRAD.findall(sample)) > 3 else "zh"
    words = re.findall(r"[a-z]+", sample.lower())
    if words and sum(w in _EN_WORDS for w in words) / len(words) > 0.06:
        return "en"  # plenty of everyday English words: don't trust a guess otherwise
    try:
        from langdetect import DetectorFactory, detect as ld  # noqa: PLC0415
        DetectorFactory.seed = 0
        code = ld(sample)
    except Exception:  # noqa: BLE001 - library missing or text too short
        return "en"
    code = {"no": "nb", "zh-cn": "zh", "zh-tw": "zt"}.get(code, code)
    return code if code in LANGUAGE_NAMES else "en"


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


# ---------------------------------------------------------------- splitting
_SENT = re.compile(r"(?<=[.!?。！？；;])\s*|\n+")


def _chunks(text: str, limit: int = 350) -> list[str]:
    out = []
    for part in _SENT.split(text or ""):
        part = part.strip()
        while len(part) > limit:  # very long sentences: cut at a space or a comma
            cut = max(part.rfind(" ", 0, limit), part.rfind("、", 0, limit), part.rfind("，", 0, limit))
            cut = cut if cut > limit // 3 else limit
            out.append(part[:cut])
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


# ---------------------------------------------------------------- providers
class DeepL:
    name = "DeepL"

    def __init__(self, key: str):
        self.key = key
        self.url = "https://api-free.deepl.com/v2/translate" if key.endswith(":fx") else "https://api.deepl.com/v2/translate"

    def translate(self, texts: list[str], src: str) -> list[str]:
        src_code = {"zt": "ZH", "zh": "ZH", "nb": "NB"}.get(src, src.upper())
        r = requests.post(self.url, headers={"Authorization": f"DeepL-Auth-Key {self.key}"},
                          data=[("target_lang", "EN-US"), ("source_lang", src_code)] + [("text", t) for t in texts],
                          timeout=60)
        r.raise_for_status()
        return [t["text"] for t in r.json()["translations"]]


class Argos:
    name = "Argos Translate"

    def __init__(self):
        import ctranslate2  # noqa: F401,PLC0415 - fail early if not installed
        import sentencepiece  # noqa: F401,PLC0415
        self._models: dict[str, tuple] = {}
        self._index: list[dict] | None = None

    def _package(self, src: str) -> Path | None:
        target = MODEL_DIR / f"{src}_en"
        if (target / "ready").exists():
            return target
        if self._index is None:
            self._index = requests.get(ARGOS_INDEX, timeout=60).json()
        pkg = next((p for p in self._index if p.get("from_code") == src and p.get("to_code") == "en"), None)
        if not pkg:
            return None
        for link in pkg.get("links", []):
            try:
                r = requests.get(link, timeout=300)
                r.raise_for_status()
                target.mkdir(parents=True, exist_ok=True)
                zipfile.ZipFile(io.BytesIO(r.content)).extractall(target)
                (target / "ready").write_text(pkg.get("package_version", ""), encoding="utf-8")
                log.info("downloaded translation model %s -> en (%d MB)", src, len(r.content) // 1_000_000)
                return target
            except (requests.RequestException, zipfile.BadZipFile) as exc:
                log.warning("translation model %s from %s failed: %s", src, link, exc)
        return None

    def _load(self, src: str):
        if src in self._models:
            return self._models[src]
        import ctranslate2  # noqa: PLC0415
        import sentencepiece  # noqa: PLC0415
        root = self._package(src)
        if root is None:
            self._models[src] = None
            return None
        model_dir = next((p.parent for p in root.rglob("model.bin")), None)
        spm_file = next(iter(root.rglob("sentencepiece.model")), None)
        if not model_dir or not spm_file:
            log.warning("translation model %s has an unexpected layout", src)
            self._models[src] = None
            return None
        prefix = ""
        meta = next(iter(root.rglob("metadata.json")), None)
        if meta:
            try:
                prefix = json.loads(meta.read_text(encoding="utf-8")).get("target_prefix", "") or ""
            except ValueError:
                pass
        model = (ctranslate2.Translator(str(model_dir), device="cpu", compute_type="int8"),
                 sentencepiece.SentencePieceProcessor(model_file=str(spm_file)), prefix)
        self._models[src] = model
        return model

    def translate(self, texts: list[str], src: str) -> list[str]:
        loaded = self._load(src)
        if loaded is None:
            raise RuntimeError(f"no {src}->en model")
        translator, spm, prefix = loaded
        out = []
        for text in texts:
            pieces = [spm.encode(c, out_type=str) for c in _chunks(text)]
            if not pieces:
                out.append("")
                continue
            kw = {"target_prefix": [[prefix]] * len(pieces)} if prefix else {}
            res = translator.translate_batch(pieces, beam_size=2, max_decoding_length=256, **kw)
            sents = []
            for r in res:
                toks = r.hypotheses[0]
                if prefix and toks and toks[0] == prefix:
                    toks = toks[1:]
                sents.append(spm.decode(toks))
            out.append(" ".join(s.strip() for s in sents if s.strip()))
        return out


# ---------------------------------------------------------------- front door
class Translator:
    def __init__(self, max_chars_per_run: int = 80_000):
        self.budget = max_chars_per_run
        self.used = 0
        self.cache: dict[str, dict] = {}
        try:
            self.cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.providers = []
        if os.environ.get("MFJ_NO_TRANSLATION"):
            return
        key = os.environ.get("DEEPL_API_KEY", "").strip()
        if key:
            self.providers.append(DeepL(key))
            self.budget = min(self.budget, 15_000)  # stay well inside DeepL's free monthly allowance
        try:
            self.providers.append(Argos())
        except ImportError:
            log.info("offline translation not installed (pip install ctranslate2 sentencepiece)")

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def translate(self, texts: list[str], src: str) -> tuple[list[str], str] | None:
        """Translate texts from src to English. Returns (translations, provider name) or None."""
        if src == "en" or not texts:
            return None
        keys = [hashlib.sha1(f"{src}|{t}".encode("utf-8")).hexdigest()[:16] for t in texts]
        if all(k in self.cache for k in keys):
            for k in keys:
                self.cache[k]["used"] = date.today().isoformat()
            return [self.cache[k]["en"] for k in keys], self.cache[keys[0]]["by"]
        size = sum(len(t) for t in texts)
        if not self.providers or self.used + size > self.budget:
            return None
        for p in self.providers:
            try:
                res = p.translate(texts, src)
            except Exception as exc:  # noqa: BLE001 - try the next provider
                log.warning("%s could not translate %s text: %s", p.name, src, exc)
                continue
            self.used += size
            for k, en in zip(keys, res):
                self.cache[k] = {"en": en, "by": p.name, "used": date.today().isoformat()}
            return res, p.name
        return None

    def save(self, keep_days: int = 200) -> None:
        cutoff = date.fromordinal(date.today().toordinal() - keep_days).isoformat()
        self.cache = {k: v for k, v in self.cache.items() if v.get("used", "") >= cutoff}
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

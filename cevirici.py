
# ── DPI farkındalığı ────────────────────────────────────────────────────────
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore
except Exception:
    pass

# ── Standart kütüphaneler ───────────────────────────────────────────────────
import importlib.util
import json
import os
import queue
import re
import subprocess
import sys
import asyncio
import threading
import time
import traceback
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# ── Zorunlu üçüncü parti ────────────────────────────────────────────────────
try:
    import customtkinter as ctk
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "customtkinter"], check=True)
    import customtkinter as ctk  # type: ignore

import tkinter as _tk  # Overlay ve RegionSelector için saf Tk

try:
    from deep_translator import GoogleTranslator
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "deep-translator"], check=True)
    from deep_translator import GoogleTranslator  # type: ignore

# ── İsteğe bağlı çeviri kütüphaneleri ──────────────────────────────────────
try:
    import google.generativeai as _gemini_lib
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "google-generativeai"], check=True)
    import google.generativeai as _gemini_lib  # type: ignore

# ── İsteğe bağlı runtime importlar ─────────────────────────────────────────
try:
    import mss
    import numpy as np
    import cv2
except ImportError:
    mss = np = cv2 = None  # type: ignore

try:
    import keyboard
except ImportError:
    keyboard = None  # type: ignore

# ── Sabitler ─────────────────────────────────────────────────────────────────
APP_VERSION = "v.2"

# ── Çeviri motoru sabitleri ───────────────────────────────────────────────────
TRANSLATION_ENGINES = ["Google Translate", "Gemini AI"]
# Fallback sırası: Gemini başarısız olursa anında Google'a döner
TRANSLATION_FALLBACK_ORDER = ["gemini", "google"]


LANGUAGES: Dict[str, str] = {
    "Otomatik": "auto", "Türkçe (TR)": "tr", "İngilizce (EN)": "en", "Rusça (RU)": "ru",
    "Japonca (JA)": "ja", "Korece (KO)": "ko", "Almanca (DE)": "de",
    "Fransızca (FR)": "fr", "Çince (ZH)": "zh-CN", "İspanyolca (ES)": "es",
    "Portekizce (PT)": "pt", "İtalyanca (IT)": "it",
}

TARGET_LANGS: Dict[str, str] = {
    "Türkçe (TR)": "tr", "İngilizce (EN)": "en",
    "Almanca (DE)": "de", "Fransızca (FR)": "fr",
    "İspanyolca (ES)": "es", "Rusça (RU)": "ru",
    "Portekizce (PT)": "pt", "İtalyanca (IT)": "it",
    "Japonca (JA)": "ja", "Korece (KO)": "ko",
    "Çince (ZH)": "zh-CN", "Lehçe (PL)": "pl",
}

FONT_COLORS: Dict[str, str] = {
    "Beyaz": "#FFFFFF",
    "Sarı": "#FFD700",
    "Turkuaz": "#00FFFF",
    "Yeşil": "#00FF88",
    "Turuncu": "#FFA500",
    "Pembe": "#FF66FF",
}

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE   = os.path.join(BASE_DIR, "settings.json")
LOCAL_MODEL_DIR = os.path.join(BASE_DIR, "local_model_en_tr")
INSTALL_LOG     = os.path.join(BASE_DIR, "install_log.txt")
APP_LOG         = os.path.join(BASE_DIR, "app_log.txt")

def _log(msg: str, level: str = "INFO") -> None:
    """
    Uygulama günlüğü — app_log.txt'e yazar.
    Sadece önemli olaylar kaydedilir; rutin durum mesajları atlanır.
    level: "INFO" | "WARN" | "ERROR" | "CRITICAL"
    """
    # Gürültü filtresi: bunlar log'a yazılmaz
    _NOISE_PREFIXES = (
        "[HybridOCR] WinOCR skor=",
        "[HybridOCR] Paralel → WinOCR=",
        "[Producer] interval=",
        "[Producer] Başladı.",
        "[Consumer] Başladı.",
        "[Consumer] Döngü tamamlandı.",
        "[Consumer] Poison-pill",
        "  torch bulundu:",
        "  NVIDIA GPU bulundu:",
        "  EasyOCR GPU motoru hazır.",
        "  torch var ama CUDA GPU bulunamadı.",
        "  Windows OCR (winrt) deneniyor...",
        "  Windows OCR hazır.",
        "  Son çare: EasyOCR CPU modu.",
        "  EasyOCR CPU motoru hazır.",
        "[HybridOCR] EasyOCR uyandırılıyor",
        "[HybridOCR] EasyOCR hazır.",
        "Aktif OCR motoru:",
        "[pip] Komutu:",
        "[pip] Çıkış kodu:",
        "[Kurulum] EasyOCR GPU kurulumu başladı.",
        "[Kurulum] opencv-python kaldırılıyor",
        "[Kaldırma] EasyOCR kaldırılıyor",
        "[Kaldırma] EasyOCR + PyTorch kaldırıldı.",
        "[Kurulum] Başarıyla tamamlandı:",
    )
    stripped = msg.strip()
    if any(stripped.startswith(p) for p in _NOISE_PREFIXES):
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(APP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass

# ── Aktif OCR motoru (thread-safe singleton) ────────────────────────────────
_active_ocr_engine: Any = None


# ═══════════════════════════════════════════════════════════════════════════════
# LRU ÖNBELLEK
# ═══════════════════════════════════════════════════════════════════════════════

class LRUCache:
    """Thread-safe LRU önbellek — en eski girdiyi atar, dict.clear() kullanmaz."""

    def __init__(self, capacity: int = 300):
        self._cap = capacity
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key not in self._d:
                return None
            self._d.move_to_end(key)
            return self._d[key]

    def put(self, key: str, value: str) -> None:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
            self._d[key] = value
            if len(self._d) > self._cap:
                self._d.popitem(last=False)


# ═══════════════════════════════════════════════════════════════════════════════
# OCR METIN ISTIKRARİLAYİCİSI
# ═══════════════════════════════════════════════════════════════════════════════

class TextStabilizer:
    """
    50 karede 45 farklı sonuç sorununu çözer.
    Kaydırmalı pencerede biriken OCR sonuçlarına
    Jaccard benzerliği ile çoğunluk oylaması uygular.
    Konsensüs oluştukluktan sonra aynı metin
    tekrar gelirse çeviriyi atlatır.
    """

    def __init__(self, window: int = 6, threshold: float = 0.50) -> None:
        self._buf: List[str]  = []
        self._window          = window
        self._threshold       = threshold
        self._last_stable     = ""

    def _jaccard(self, a: str, b: str) -> float:
        sa = set(a.lower().split())
        sb = set(b.lower().split())
        if not sa and not sb:
            return 1.0
        u = len(sa | sb)
        return (len(sa & sb) / u) if u else 0.0

    def push(self, text: str) -> Optional[str]:
        """
        Yeni OCR metnini ekle.
        Konsensüs oluşmuşsa ve son gönderilen metinden
        farklıysa döndür; aksi halde None.
        """
        t = text.strip()
        if not t:
            return None
        self._buf.append(t)
        if len(self._buf) > self._window:
            self._buf.pop(0)
        min_buf = 2 if len(t) <= 10 else 3
        if len(self._buf) < min_buf:
            return None

        # Her metin kaç diğeriyle threshold üzeri benzerlik gösteriyor?
        n = len(self._buf)
        scores = [0] * n
        for i in range(n):
            for j in range(n):
                if i != j and self._jaccard(self._buf[i], self._buf[j]) >= self._threshold:
                    scores[i] += 1

        best = max(range(n), key=lambda i: scores[i])
        if scores[best] < 2:          # konsensüs yok, bekle
            return None

        consensus = self._buf[best]
        if consensus == self._last_stable:  # değişmedi, atlat
            return None
        self._last_stable = consensus
        return consensus

    def reset(self) -> None:
        self._buf.clear()
        self._last_stable = ""


# ═══════════════════════════════════════════════════════════════════════════════
# ÇEVİRİ MOTORU — Google / OpenAI / Claude otomatik fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TranslationEngine:
    """
    Birden fazla çeviri arka ucunu soyutlar.
    Öncelik sırası: Seçilen motor dener, hata alırsa doğrudan Google'a (fallback) geçer.
    """

    _MAX_RETRIES   = 2          # Her motor için deneme sayısı
    _RETRY_DELAY   = 0.4        # saniye

    def __init__(self, app: "App") -> None:
        self._app = app

    def translate(self, text: str, src: str, tgt: str) -> Tuple[str, str]:
        selected   = self._app.translation_engine_var.get()
        order      = self._build_order(selected)

        for engine_key in order:
            try:
                result = self._call(engine_key, text, src, tgt)
                if result and result.strip():
                    if engine_key != selected:
                        _log(f"[Çeviri] {selected} başarısız, {engine_key} kullanıldı.", "WARN")
                    return result.strip(), engine_key
            except Exception as exc:
                _log(f"[Çeviri] {engine_key} hatası: {exc}", "WARN")
                continue

        return text, "google"   # son çare: orijinali göster

    def _build_order(self, selected: str) -> List[str]:
        full = TRANSLATION_FALLBACK_ORDER[:]    # ["gemini", "google"]
        if selected in full:
            full.remove(selected)
            full.insert(0, selected)
        return full

    def _call(self, engine_key: str, text: str, src: str, tgt: str) -> str:
        if engine_key == "google":
            return self._google(text, src, tgt)
        elif engine_key == "gemini":
            return self._gemini(text, src, tgt)
        return text

    def _google(self, text: str, src: str, tgt: str) -> str:
        for attempt in range(self._MAX_RETRIES):
            try:
                return GoogleTranslator(source=src, target=tgt).translate(text) or text
            except Exception as exc:
                if attempt < self._MAX_RETRIES - 1:
                    time.sleep(self._RETRY_DELAY)
                else:
                    raise exc
        return text

    def _gemini(self, text: str, src: str, tgt: str) -> str:
        api_key = self._app.gemini_key_var.get().strip()
        if not api_key:
            raise ValueError("Gemini API key girilmemiş")
        if _gemini_lib is None:
            raise ImportError("google-generativeai paketi kurulu değil")

        _gemini_lib.configure(api_key=api_key)
        lang_name = self._lang_name(tgt)
        
        prompt = (
            f"You are a professional game translator. Translate the following game dialog text to {lang_name}. "
            f"Preserve character names, formatting, and line breaks exactly. "
            f"Understand the context, slang and idioms. Return ONLY the translated text, nothing else.\n\n{text}"
        )
        
        # OYUN ÇEVİRİSİ İÇİN GÜVENLİK FİLTRELERİNİ KAPAT (Şiddet, argo vb. engellenmesin diye)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]

        for attempt in range(self._MAX_RETRIES):
            try:
                model = _gemini_lib.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt, safety_settings=safety_settings)
                if response.text:
                    # Başarılı olursa durum çubuğunu sessizce yeşile çevir (Limit uyarısından çıkış için)
                    self._app.root.after(0, lambda: getattr(self._app, '_api_status_lbl', None) and self._app._api_status_lbl.configure(text="✓ API Aktif", text_color="#7EE787"))
                    return response.text.strip()
                return text
            except Exception as exc:
                err_msg = str(exc).lower()
                # KOTA VEYA LİMİT AŞIMI KONTROLÜ
                if "429" in err_msg or "quota" in err_msg or "exhausted" in err_msg:
                    self._app.root.after(0, lambda: getattr(self._app, '_api_status_lbl', None) and self._app._api_status_lbl.configure(text="⚠ API Limiti Doldu", text_color="#DA3633"))
                
                if attempt < self._MAX_RETRIES - 1:
                    time.sleep(self._RETRY_DELAY)
                else:
                    raise exc
        return text

    @staticmethod
    def _lang_name(code: str) -> str:
        """Dil kodunu insan okuyabilir isme çevirir (OpenAI/Claude promptu için)."""
        _MAP = {
            "tr": "Turkish", "en": "English", "ru": "Russian",
            "ja": "Japanese", "ko": "Korean", "de": "German",
            "fr": "French", "zh-CN": "Chinese (Simplified)",
            "es": "Spanish", "pt": "Portuguese", "it": "Italian",
            "pl": "Polish",
        }
        return _MAP.get(code, code)


class EasyOCREngine:
    def __init__(self, use_gpu: bool):
        import easyocr
        self._reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
        self.use_gpu = use_gpu

    def read(self, image: Any) -> List[Tuple[Any, str, float]]:
        return self._reader.readtext(image, detail=1, paragraph=False)


class WindowsOCREngine:
    """
    Windows OCR motoru — Python 3.11+ uyumlu yeni winrt paket yapısı.

    Eski paket (bozuk):  winrt.windows.media.ocr
    Yeni paket (doğru):  winrt.windows.media.ocr   ← winrt-Windows.Media.Ocr pip paketiyle gelir

    Yeni winrt sürümlerinde (0.10+) alt paketler ayrı pip paketleri olarak dağıtılıyor.
    Kurulum: pip install winrt-Windows.Media.Ocr winrt-Windows.Globalization
                         winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams
                         winrt-Windows.Foundation winrt-Windows.Foundation.Collections
    """

    def __init__(self, lang_tag: str = "en-US"):
        self.lang_tag = lang_tag
        self._engine_cache: Any = None   # OcrEngine tekrar tekrar oluşturulmasın

    def _get_ocr_engine(self) -> Any:
        """OcrEngine'i bir kez oluştur, önbellekte tut."""
        if self._engine_cache is not None:
            return self._engine_cache
        try:
            # Yeni winrt paket yapısı (winrt-Windows.* pip paketleri)
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine
        except ImportError as e:
            _log(f"[WinOCR] winrt alt paketleri eksik: {e}  →  pip install winrt-Windows.Media.Ocr ...", "ERROR")
            raise

        try:
            lang = Language(self.lang_tag)
            engine = OcrEngine.try_create_from_language(lang)
        except Exception:
            engine = None

        if engine is None:
            try:
                engine = OcrEngine.try_create_from_user_profile_languages()
            except Exception:
                engine = None

        if engine is None:
            _log("[WinOCR] OcrEngine oluşturulamadı — Windows dil paketi eksik olabilir.", "ERROR")
            raise RuntimeError("WinOCR OcrEngine oluşturulamadı")

        self._engine_cache = engine
        return engine

    async def _recognize(self, np_image: Any) -> Any:
        import io
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import (
            InMemoryRandomAccessStream,
            DataWriter,
        )
        from PIL import Image

        engine = self._get_ocr_engine()

        # numpy (H,W) veya (H,W,3/4) → RGBA PIL Image
        img_arr = np_image
        if img_arr.ndim == 2:
            pil = Image.fromarray(img_arr).convert("RGBA")
        elif img_arr.shape[2] == 4:
            pil = Image.fromarray(img_arr, "RGBA")
        else:
            pil = Image.fromarray(img_arr, "RGB").convert("RGBA")

        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        data = buf.getvalue()

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(data)   # winrt write_bytes bytes bekler
        await writer.store_async()
        stream.seek(0)

        decoder = await BitmapDecoder.create_async(stream)
        bitmap  = await decoder.get_software_bitmap_async()
        return await engine.recognize_async(bitmap)

    def read(self, np_image: Any) -> List[Tuple[Any, str, float]]:
        import traceback
        lines: List[Tuple[Any, str, float]] = []
        try:
            # Her çağrıda yeni event loop oluştur (thread güvenliği)
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(self._recognize(np_image))
            finally:
                loop.close()

            if not result:
                return lines

            # result.lines property'sine DOKUNMA.
            # Herhangi bir erişim (for, .size, list()) winrt'nin
            # winrt.windows.foundation.collections modülünü lazy yüklemesini
            # tetikler — paket eksikse ModuleNotFoundError fırlatır.
            #
            # result.text ise doğrudan string döndürür, collections gerekmez.
            full_text: str = getattr(result, "text", "") or ""
            if not full_text.strip():
                return lines

            img_h = np_image.shape[0] if hasattr(np_image, "shape") else 100
            img_w = np_image.shape[1] if hasattr(np_image, "shape") else 400
            text_lines = [ln for ln in full_text.splitlines() if ln.strip()]
            line_h = max(1, img_h // max(len(text_lines), 1))
            for idx, text in enumerate(text_lines):
                y0 = idx * line_h
                y1 = y0 + line_h
                bbox = [[0, y0], [img_w, y0], [img_w, y1], [0, y1]]
                lines.append((bbox, text.strip(), 0.9))
        except Exception as exc:
            _log(f"[WinOCR.read Hatası] {exc}\n{traceback.format_exc()}", "ERROR")
        return lines




# ═══════════════════════════════════════════════════════════════════════════════
# METİN KALİTE PUANLAYICI (Heuristic Scorer)
# ═══════════════════════════════════════════════════════════════════════════════

class TextQualityScorer:
    """
    OCR çıktısının gerçek metin mi yoksa arka plan gürültüsü mü olduğunu
    0–100 arası bir güven skoru ile değerlendirir.
    """
    VOWELS     = set("aeiouAEIOU")
    MAX_REPEAT = 3  # art arda bu kadar aynı harf → gürültü

    @classmethod
    def score(cls, text: str) -> int:
        t = text.strip()
        if not t:
            return 0
        letters  = [c for c in t if c.isalpha()]
        alphanum = [c for c in t if c.isalnum()]
        total    = len(t)
        sc = 50

        # ── Kriter 1: Uzunluk ───────────────────────────────────────
        if total < 3:
            sc -= 40
        elif total < 6:
            sc -= 15
        elif total >= 15:
            sc += 10

        # ── Kriter 2: Sesli harf testi ──────────────────────────────
        if letters:
            vowel_ratio = sum(1 for c in letters if c in cls.VOWELS) / len(letters)
            if vowel_ratio == 0:
                sc -= 35
            elif vowel_ratio < 0.10:
                sc -= 20

        # ── Kriter 3: Alfanümerik yoğunluk ─────────────────────────
        if total > 0:
            density = len(alphanum) / total
            if density < 0.40:
                sc -= 25
            elif density >= 0.75:
                sc += 10

        # ── Kriter 4: Art arda tekrar harf (çimen/çit/HUD gürültüsü)
        if re.search(r'(.)\1{' + str(cls.MAX_REPEAT) + r',}', t, re.IGNORECASE):
            sc -= 40

        return max(0, min(100, sc))


# ═══════════════════════════════════════════════════════════════════════════════
# HİBRİT OCR MOTORU
# ═══════════════════════════════════════════════════════════════════════════════

class HybridOCREngine:
    """
    Standart Mod (Tasarruf)  : WindowsOCR → skor < eşik → EasyOCR fallback.
    Agresif Mod  (Performans): İki motoru ThreadPoolExecutor ile paralel çalıştırır,
                               daha yüksek skorlu sonucu seçer.
    EasyOCR lazy init — belleğe sadece ihtiyaç duyulduğunda yüklenir.
    """
    QUALITY_THRESHOLD = 40

    def __init__(self, hybrid_mode_var: "ctk.StringVar") -> None:
        self._win        = WindowsOCREngine("en-US")
        self._easy: Optional["EasyOCREngine"] = None   # lazy
        self._mode       = hybrid_mode_var            # "standard" | "aggressive"
        self._easy_lock  = threading.Lock()

    # ── EasyOCR lazy yükleme ────────────────────────────────────────────────
    def _get_easy(self) -> "EasyOCREngine":
        with self._easy_lock:
            if self._easy is None:
                use_gpu = False
                try:
                    import torch
                    use_gpu = torch.cuda.is_available()
                except Exception:
                    pass
                _log(f"[HybridOCR] EasyOCR uyandırılıyor (gpu={use_gpu})…")
                self._easy = EasyOCREngine(use_gpu=use_gpu)
                _log(f"[HybridOCR] EasyOCR hazır.")
            return self._easy

    # ── İç okuma yardımcıları ───────────────────────────────────────────────
    def _win_read(self, image: Any) -> List[Tuple[Any, str, float]]:
        return self._win.read(image)

    def _easy_read(self, image: Any) -> List[Tuple[Any, str, float]]:
        return self._get_easy().read(image)

    # ── Genel API ───────────────────────────────────────────────────────────
    def read(self, image: Any) -> List[Tuple[Any, str, float]]:
        if self._mode.get() == "aggressive":
            return self._parallel_read(image)
        return self._fallback_read(image)

    def _fallback_read(self, image: Any) -> List[Tuple[Any, str, float]]:
        """Standart Mod: WinOCR dene → yetersizse EasyOCR'a devret."""
        win_result = self._win_read(image)
        win_text   = _build_lines_static(win_result)
        sc = TextQualityScorer.score(win_text)
        _log(f"[HybridOCR] WinOCR skor={sc}")
        if sc >= self.QUALITY_THRESHOLD:
            return win_result
        _log(f"[HybridOCR] Skor düşük ({sc}<{self.QUALITY_THRESHOLD}) → EasyOCR", "WARN")
        return self._easy_read(image)

    def _parallel_read(self, image: Any) -> List[Tuple[Any, str, float]]:
        """Agresif Mod: iki motoru paralel çalıştır, kaliteli olanı seç."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results: Dict[str, List] = {}
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = {
                ex.submit(self._win_read,  image): "win",
                ex.submit(self._easy_read, image): "easy",
            }
            for fut in as_completed(futs):
                key = futs[fut]
                try:
                    results[key] = fut.result()
                except Exception as exc:
                    _log(f"[HybridOCR parallel] {key} hata: {exc}", "ERROR")
                    results[key] = []
        win_txt  = _build_lines_static(results.get("win", []))
        easy_txt = _build_lines_static(results.get("easy", []))
        win_sc   = TextQualityScorer.score(win_txt)
        easy_sc  = TextQualityScorer.score(easy_txt)
        _log(f"[HybridOCR] Paralel → WinOCR={win_sc}, EasyOCR={easy_sc}")
        return results["win"] if win_sc >= easy_sc else results.get("easy", [])


def _build_lines_static(ocr_result: Any, gap: int = 15) -> str:
    """TaskEngine._build_lines'ın bağımsız versiyonu — HybridOCREngine kullanır."""
    if not ocr_result:
        return ""
    try:
        items = sorted(
            [((b[0][1] + b[1][1]) / 2, t) for b, t, _ in ocr_result],
            key=lambda x: x[0],
        )
        lines: List[str] = []
        cur_y, cur_words = items[0][0], [items[0][1]]
        for y, word in items[1:]:
            if abs(y - cur_y) <= gap:
                cur_words.append(word)
            else:
                lines.append(" ".join(cur_words))
                cur_y, cur_words = y, [word]
        lines.append(" ".join(cur_words))
        return "\n".join(lines)
    except Exception:
        return ""



# ═══════════════════════════════════════════════════════════════════════════════
# DONANIM TESPİTİ
# ═══════════════════════════════════════════════════════════════════════════════

class HardwareDetector:

    @staticmethod
    def detect() -> Dict[str, Any]:
        import traceback
        info: Dict[str, Any] = {"gpu": "Bilinmiyor", "engine_name": "", "engine": None}
        _log(f"=== Donanım Taraması Başlıyor (Python {sys.version}) ===", "INFO")

        # 1. EasyOCR GPU dene
        try:
            import torch
            _log(f"  torch bulundu: {torch.__version__}")
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
                vram = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
                info["gpu"]         = f"{name} ({vram} MB)"
                info["engine_name"] = f"⚡ EasyOCR GPU — {name}"
                _log(f"  NVIDIA GPU bulundu: {name} ({vram} MB). EasyOCR yükleniyor...")
                info["engine"]      = EasyOCREngine(use_gpu=True)
                _log("  EasyOCR GPU motoru hazır.")
                return info
            else:
                _log("  torch var ama CUDA GPU bulunamadı.")
        except Exception as e:
            _log(f"  EasyOCR/torch hatası: {e}\n{traceback.format_exc()}", "ERROR")

        # 2. Windows OCR (winrt) dene — yeni paket yapısı: winrt-Windows.Media.Ocr
        try:
            _log("  Windows OCR (winrt) deneniyor...")
            from winrt.windows.media.ocr import OcrEngine  # type: ignore  # noqa: F401
            gpu_name = HardwareDetector._gpu_name()
            info["gpu"]         = gpu_name
            info["engine_name"] = f"💨 Windows OCR — {gpu_name}"
            info["engine"]      = WindowsOCREngine("en-US")
            _log(f"  Windows OCR hazır. GPU: {gpu_name}")
            return info
        except Exception as e:
            _log(f"  Windows OCR hatası: {e}\n{traceback.format_exc()}", "ERROR")

        # 3. Son çare: EasyOCR CPU
        _log("  Son çare: EasyOCR CPU modu.")
        info["engine_name"] = "🐌 EasyOCR CPU (GPU / WinOCR bulunamadı)"
        info["engine"]      = EasyOCREngine(use_gpu=False)
        _log("  EasyOCR CPU motoru hazır.")
        return info

    @staticmethod
    def _gpu_name() -> str:
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject Win32_VideoController | Select-Object -First 1).Name"],
                capture_output=True, text=True, timeout=4,
            )
            name = r.stdout.strip()
            return name if name else "GPU Bilinmiyor"
        except Exception:
            return "GPU Bilinmiyor"


# ═══════════════════════════════════════════════════════════════════════════════
# GÖRÜNTÜ İŞLEME (OCR Ön İşleme)
# ═══════════════════════════════════════════════════════════════════════════════

class OCRProcessor:

    @staticmethod
    def process(image: Any) -> Tuple[Any, int]:
        """
        Çift-mod OCR ön işleme:
        - Şeritli mod: HSV maskeleme (sarı/beyaz) — yüksek pixel_count
        - Şeritsiz mod: adaptif eşikleme — düşük pixel_count durumunda devreye girer
        """
        if isinstance(image, np.ndarray):
            img = image.copy()
            if img.ndim == 3 and img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        else:
            img = np.array(image)
            if img.ndim == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        h, w = img.shape[:2]
        img  = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # ── Şeritli mod (HSV mask) ─────────────────────────────────────────
        hsv    = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        white  = cv2.inRange(hsv, np.array([0,  0,   110]), np.array([180,  65, 255]))
        yellow = cv2.inRange(hsv, np.array([15, 60,  130]), np.array([ 45, 255, 255]))
        mask   = cv2.dilate(cv2.bitwise_or(white, yellow), np.ones((3, 3), np.uint8), iterations=1)
        pixel_count = int(np.sum(mask > 0))

        gray   = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        smooth = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
        clahe  = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        enhanced_clahe = clahe.apply(smooth)

        if pixel_count >= 80:
            # Şeritli/renkli metin: Otsu eşikleme
            _, enh = cv2.threshold(enhanced_clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if np.mean(enh) < 128:
                enh = cv2.bitwise_not(enh)
            return enh, pixel_count

        # ── Şeritsiz mod (adaptif) ─────────────────────────────────────────
        # God of War, Horizon, Ghost of Tsushima gibi oyunlarda arka plansız metin
        # 1) Adaptif threshold — lokal kontrast ile metin ayrıştırma
        adap = cv2.adaptiveThreshold(
            enhanced_clahe, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 8
        )
        # 2) Morfolojik açma — ince gürültüyü sil
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        adap   = cv2.morphologyEx(adap, cv2.MORPH_OPEN, kernel)
        # 3) Sahte piksel sayısı — adaptif modda farklı hesap
        adap_px = int(np.sum(adap > 0))
        return adap, adap_px

    @staticmethod
    def find_dialog_bubbles(image: Any, min_area: int = 4000) -> List[Any]:
        """
        Konuşma balonu / diyalog kutusu tespiti.

        Yaklaşım:
          1. Görüntüyü gri tonlamaya çevir, Canny kenar tespiti uygula.
          2. Konturları bul; dikdörtgen veya oval formdaki büyük, dolu bölgeleri seç.
          3. Her aday bölgeyi kırp ve OCR ön işleme için döndür.

        Döndürür: kırpılmış numpy görüntü listesi (boşsa boş liste).
        Kullanım:
          crops = OCRProcessor.find_dialog_bubbles(frame)
          if crops:
              for crop in crops:
                  enh, px = OCRProcessor.process(crop)
                  results = engine.read(enh)
        """
        if np is None or cv2 is None:
            return []

        if isinstance(image, np.ndarray):
            img = image.copy()
            if img.ndim == 3 and img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        else:
            img = np.array(image)
            if img.ndim == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Hafif blur → kenar tespiti
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges   = cv2.Canny(blurred, 30, 100)

        # Morfolojik kapama: balonu kapalı bir şekle dönüştür
        close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        closed  = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, close_k, iterations=2)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        crops: List[Any] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue

            # Dikdörtgensellik kontrolü: bounding rect doluluk oranı
            bx, by, bw, bh = cv2.boundingRect(cnt)
            if bw < 40 or bh < 15:
                continue
            fill_ratio = area / (bw * bh)
            if fill_ratio < 0.30:  # çok seyrek → muhtemelen sahte kontur
                continue

            # Görüntünün %90'ından büyükse tüm ekran seçilmiş demektir — atla
            if bw * bh > 0.90 * w * h:
                continue

            # Kenar boşluğu ekle
            pad = 6
            x1 = max(0, bx - pad)
            y1 = max(0, by - pad)
            x2 = min(w, bx + bw + pad)
            y2 = min(h, by + bh + pad)
            crops.append(img[y1:y2, x1:x2])

        return crops



# ═══════════════════════════════════════════════════════════════════════════════
# ŞEFFAF OVERLAY
# ═══════════════════════════════════════════════════════════════════════════════

class Overlay:
    """
    Ekran üstü şeffaf altyazı — Waterfall (Şelale) modunda 3 satır.

    Satır düzeni (alttan üste):
        slot[2] → Alt  (YENİ)   : parlak, tam boyut
        slot[1] → Orta (ÖNCEKİ): yarısaydam
        slot[0] → Üst  (ESKİ)  : soluk/küçük
    """

    _STROKE_OFFSETS = [
        (-2, -2), (0, -2), (2, -2),
        (-2,  0),          (2,  0),
        (-2,  2), (0,  2), (2,  2),
    ]

    # Şelale stil tablosu: (alpha_factor, size_delta, color_override_or_None)
    _SLOT_STYLE = [
        (0.0, -4, "#585858"),   # slot 0: eski — soluk gri, küçük font
        (0.0, -2, "#AAAAAA"),   # slot 1: önceki — yarı beyaz
        (0.0,  0,  None),       # slot 2: yeni — kullanıcı rengi
    ]
    _AUTO_CLEAR_SECS = 6        # saniye sonra tüm satırları temizle

    def __init__(
        self,
        region: Tuple[int, int, int, int],
        font_size: int = 16,
        font_family: str = "Segoe UI",
        font_color: str = "#FFFFFF",
        font_bold: bool = True,
    ):
        x1, y1, x2, y2 = region
        self.width      = max(x2 - x1, 700)
        self.font_size  = font_size
        self.font_family= font_family
        self.font_color = font_color
        self.font_bold  = font_bold
        self.visible    = False
        self._dx = self._dy = 0
        self._lines: List[str] = ["", "", ""]   # [eski, önceki, yeni]
        self._clear_timer: Optional[str] = None  # Tkinter after() id
        self._timer_end_time: float = 0.0

        tmp = _tk.Tk(); tmp.withdraw()
        sw = tmp.winfo_screenwidth()
        sh = tmp.winfo_screenheight()
        tmp.destroy()
        self._pos_x = max(0, (sw - self.width) // 2)
        self._pos_y = int(sh * 0.80)
        self._screen_w = sw
        self._screen_h = sh

        self.root = _tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#010101")
        self.root.attributes("-transparentcolor", "#010101")
        self.root.geometry(f"{self.width}x160+{self._pos_x}+{self._pos_y}")

        # Canvas: şeffaf arka plan (#010101 transparent renk)
        self.canvas = _tk.Canvas(
            self.root, bg="#010101", highlightthickness=0,
            width=self.width, height=160,
        )
        self.canvas.pack(fill=_tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>",     self._drag_move)

        self._stroke_ids: List[int] = []
        self._text_id: int = 0
        self.root.withdraw()

    def _font_tuple(self, delta: int = 0) -> tuple:
        wt = "bold" if self.font_bold else "normal"
        return (self.font_family, max(9, self.font_size + delta), wt)

    # ── Waterfall API ─────────────────────────────────────────────────────────
    def push_line(self, text: str) -> None:
        """Yeni çeviriyi alta ekle; eskilerini yukarı kaydır."""
        if not text or not text.strip():
            return
        if not self.root.winfo_exists():
            return
        self._lines[0] = self._lines[1]
        self._lines[1] = self._lines[2]
        self._lines[2] = text.strip()
        self._render()
        if not self.visible:
            self.root.deiconify()
            self.root.lift()
            self.visible = True
        new_delay = self._clear_duration(text)
        if self._clear_timer is None or new_delay > self._remaining_delay():
            self._reset_clear_timer(text)

    def _clear_duration(self, text: str) -> int:
        n = len(text)
        words = len(text.split())
        reading_ms = max(5_000, words * 400 + 2_000)
        if n < 15:
            return 5_500
        if n > 80:
            return min(reading_ms, 12_000)
        return min(reading_ms, 8_000)

    def _reset_clear_timer(self, text: str = "") -> None:
        if self._clear_timer is not None:
            try:
                self.root.after_cancel(self._clear_timer)
            except Exception:
                pass
        delay = self._clear_duration(text) if text else self._AUTO_CLEAR_SECS * 1000
        self._timer_end_time = time.monotonic() + (delay / 1000.0)
        self._clear_timer = self.root.after(delay, self._auto_clear)

    def _remaining_delay(self) -> int:
        """Aktif timer'ın gerçek kalan süresini ms cinsinden döndür."""
        return max(0, int((self._timer_end_time - time.monotonic()) * 1000))

    def _auto_clear(self) -> None:
        """Zaman aşımı: tüm satırları temizle ve overlay'i gizle."""
        self._lines = ["", "", ""]
        self._clear_timer = None
        if self.root.winfo_exists():
            self.canvas.delete("all")
            self.root.withdraw()
            self.visible = False

    def _render(self) -> None:
        """
        3 satırı bbox tabanlı dinamik dikey yerleşim ile çiz.
        Alt→Üst istifle: slot[2] (yeni) referans; slot[1] onun üzeri; slot[0] onun da üzeri.
        Eğer toplam yükseklik canvas'a sığmazsa slot[0] otomatik temizlenir.
        """
        if not self.root.winfo_exists():
            return
        self.canvas.delete("all")

        PADDING  = 16   # satırlar arası boşluk (piksel)
        MARGIN_Y = 10   # üst/alt kenar boşluğu
        MAX_H    = 420  # canvas azami yüksekliği (clipping son sınır)
        cx = self.width // 2

        # ── Geçici canvas üzeriðne metin çizerek gerçek yükseklikleri ölç
        def _measure(txt: str, delta: int) -> int:
            """Bu metni bu fontta çiz, bbox yüksekliğini döndür, sonra sil."""
            font = self._font_tuple(delta)
            tid  = self.canvas.create_text(
                cx, 9999, text=txt, font=font,
                width=self.width - 48, justify=_tk.CENTER, anchor="n",
            )
            self.canvas.update_idletasks()
            bb = self.canvas.bbox(tid)
            self.canvas.delete(tid)
            return (bb[3] - bb[1]) if bb else (max(9, self.font_size + delta) + 4)

        # Yükseklikleri ölç: [slot0_h, slot1_h, slot2_h]  (0 = boş slot)
        raw_h = [
            _measure(self._lines[i], self._SLOT_STYLE[i][1]) if self._lines[i] else 0
            for i in range(3)
        ]

        # Toplam hesapla; taşarsa slot[0] önce temizlenir
        def total(heights: List[int]) -> int:
            filled = [h for h in heights if h > 0]
            return sum(filled) + PADDING * max(len(filled) - 1, 0) + MARGIN_Y * 2

        if total(raw_h) > MAX_H and raw_h[0]:
            raw_h[0] = 0
            self._lines[0] = ""

        canvas_h = max(total(raw_h), 50)

        # ── Alt→Üst istifle: slot[2] en alt, slot[0] en üst
        # Referans: slot[2] yükseklinin alt kenarı = canvas_h - MARGIN_Y
        bottom = canvas_h - MARGIN_Y
        y_centers: List[int] = [-1, -1, -1]

        for i in range(2, -1, -1):   # 2 → 1 → 0
            h = raw_h[i]
            if h == 0:
                continue
            cy = bottom - h // 2
            y_centers[i] = cy
            bottom = bottom - h - PADDING

        # Canvas yüksekliğini aç: çizim öncesi olmalı
        self.canvas.config(width=self.width, height=canvas_h)
        self.root.geometry(f"{self.width}x{canvas_h}+{self._pos_x}+{self._pos_y}")
        self.root.update_idletasks()

        # ── Çiz
        for i, (_, sz_delta, clr_override) in enumerate(self._SLOT_STYLE):
            txt = self._lines[i]
            if not txt or y_centers[i] < 0:
                continue
            cy    = y_centers[i]
            font  = self._font_tuple(sz_delta)
            color = clr_override if clr_override else self.font_color
            for dx, dy in self._STROKE_OFFSETS:
                self.canvas.create_text(
                    cx + dx, cy + dy, text=txt,
                    font=font, fill="#000000",
                    width=self.width - 48, justify=_tk.CENTER, anchor="center",
                )
            self.canvas.create_text(
                cx, cy, text=txt, font=font, fill=color,
                width=self.width - 48, justify=_tk.CENTER, anchor="center",
            )

    def _drag_start(self, e: Any) -> None:
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e: Any) -> None:
        nx = self.root.winfo_x() + e.x - self._dx
        ny = self.root.winfo_y() + e.y - self._dy
        self._pos_x, self._pos_y = nx, ny
        self.root.geometry(f"+{nx}+{ny}")

    # Geriye dönük uyumluluk
    def show_text(self, text: str) -> None:
        self.push_line(text)

    def hide(self) -> None:
        if self.root.winfo_exists() and self.visible:
            self.root.withdraw()
            self.visible = False

    def temp_hide(self) -> None:
        if self.root.winfo_exists():
            self.root.withdraw()

    def temp_show(self) -> None:
        if self.root.winfo_exists() and self.visible:
            self.root.deiconify()

    def reset_position(self) -> None:
        self._pos_x = (self._screen_w - self.width) // 2
        self._pos_y = int(self._screen_h * 0.80)
        self.root.geometry(f"+{self._pos_x}+{self._pos_y}")
        if self.visible:
            self.root.deiconify()

    def set_style(self, size: int, family: str, color: str, bold: bool) -> None:
        self.font_size  = size
        self.font_family= family
        self.font_color = color
        self.font_bold  = bold
        if any(self._lines):
            self._render()

    def destroy(self) -> None:
        if self._clear_timer is not None:
            try:
                self.root.after_cancel(self._clear_timer)
            except Exception:
                pass
        if self.root.winfo_exists():
            self.root.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
# BÖLGE SEÇİCİ
# ═══════════════════════════════════════════════════════════════════════════════

class RegionSelector:
    _is_open = False  # Sınıf seviyesinde KESİN kilit

    def __init__(self, callback: Any):
        # 1. SPAM KİLİDİ: Eğer zaten bir ekran açıksa, ikincisini asla açma!
        if RegionSelector._is_open:
            return
        RegionSelector._is_open = True

        self.callback = callback
        self._sx: Optional[int] = None
        self._sy: Optional[int] = None
        self._rect: Optional[int] = None

        self.root = _tk.Toplevel()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.28)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")

        # 2. ODAK REHİN ALMA (ESC ve Sağ tıkın kesin çalışması için)
        self.root.focus_force()   # Pencereyi zorla en öne al
        self.root.grab_set()      # Tüm klavye ve fareyi bu pencereye KİLİTLE

        self.canvas = _tk.Canvas(self.root, cursor="cross", bg="black", highlightthickness=0)
        self.canvas.pack(fill=_tk.BOTH, expand=True)

        _tk.Label(
            self.root,
            text="🎯  Çevrilecek alanı sürükleyerek seçin  —  SAĞ TIK veya ESC = İptal",
            font=("Segoe UI", 18, "bold"),
            bg="black", fg="#00FF88", padx=20, pady=14,
        ).place(relx=0.5, rely=0.07, anchor="center")

        self.canvas.bind("<ButtonPress-1>",  self._press)
        self.canvas.bind("<B1-Motion>",      self._drag)
        self.canvas.bind("<ButtonRelease-1>",self._release)
        
        # Kapatma (İptal) Kısayolları
        self.root.bind("<Escape>",   lambda _e: self._cancel())
        self.canvas.bind("<Button-3>", lambda _e: self._cancel()) # Sağ tık

    def _press(self, e: Any) -> None:
        self._sx = self.root.winfo_pointerx()
        self._sy = self.root.winfo_pointery()
        if self._rect:
            self.canvas.delete(self._rect)
        self._rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#00FF88", width=2)

    def _drag(self, e: Any) -> None:
        if self._rect and self._sx is not None:
            rx = self._sx - self.root.winfo_rootx()
            ry = self._sy - self.root.winfo_rooty()
            self.canvas.coords(self._rect, rx, ry, e.x, e.y)

    def _release(self, e: Any) -> None:
        RegionSelector._is_open = False
        self.root.grab_release()  # Rehin alınan donanımları serbest bırak
        if self._sx is None:
            self.root.destroy(); self.callback(None); return
        ex, ey = self.root.winfo_pointerx(), self.root.winfo_pointery()
        x1, y1 = min(self._sx, ex), min(self._sy, ey)
        x2, y2 = max(self._sx, ex), max(self._sy, ey)
        self.root.destroy()
        self.callback((x1, y1, x2, y2) if (x2 - x1 > 30 and y2 - y1 > 15) else None)

    def _cancel(self) -> None:
        RegionSelector._is_open = False
        self.root.grab_release()  # Rehin alınan donanımları serbest bırak
        self.root.destroy()
        self.callback(None)


# ═══════════════════════════════════════════════════════════════════════════════
# TARAMA MOTORU (Thread)
# ═══════════════════════════════════════════════════════════════════════════════

class TaskEngine:
    """
    Producer-Consumer mimarisi:
      Producer (_loop)       : Ekran tarama + OCR + Jaccard dedup → _tq'ya at
      Consumer (_consumer_loop): _tq'yu dinle → GoogleTranslate → UI kuyruğuna gönder
    İki thread bağımsız çalışır; çeviri API'si Producer'ı bloklayamaz.
    """

    # Jaccard dedup eşiği — bu değerin ALTINDA yeni diyalog sayılır
    DEDUP_THRESHOLD = 0.40

    def __init__(self, app: "App"):
        self.app      = app
        self.region:  Optional[Tuple[int, int, int, int]] = None
        self.overlay: Optional[Overlay] = None
        self.running  = False
        self._thread:   Optional[threading.Thread] = None
        self._consumer: Optional[threading.Thread] = None
        self._tracker:  Optional[threading.Thread] = None   # pencere takip thread'i
        self._cache   = LRUCache(300)
        self._stab    = TextStabilizer(window=6, threshold=0.50)
        self._tq: queue.Queue = queue.Queue(maxsize=3)   # çeviri kuyruğu
        self.q:   queue.Queue = queue.Queue()             # UI kuyruğu
        # Pencere takibi — manuel seçimde None, otomatik takipte HWND
        self._tracked_hwnd: Optional[int] = None
        self._region_offset: Optional[Tuple[int, int, int, int]] = None

    # ── Yaşam döngüsü ─────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.region or self.running:
            return
        cfg = self.app.get_overlay_config()
        self.overlay = Overlay(self.region, **cfg)
        
        # --- AKILLI KONUMLANDIRMA (Seçili Alanın Üstü) ---
        rx1, ry1, rx2, ry2 = self.region
        gap = 20          # Orijinal metinle çeviri arasındaki boşluk
        ov_h = 160        # Overlay'in tahmini yüksekliği
        
        new_y = ry1 - ov_h - gap
        if new_y < 0:     # Eğer ekranın çok üstündeyse ve taşarsa çerçevenin altına al
            new_y = ry2 + gap
            
        # X ekseninde seçili alanı ortala
        mid_x = rx1 + ((rx2 - rx1) // 2)
        new_x = max(0, mid_x - (self.overlay.width // 2))
        
        self.overlay._pos_x = new_x
        self.overlay._pos_y = new_y
        self.overlay.root.geometry(f"+{self.overlay._pos_x}+{self.overlay._pos_y}")
        # ------------------------------------------------
        
        self.running = True
        self._thread   = threading.Thread(target=self._loop,          daemon=True)
        self._consumer = threading.Thread(target=self._consumer_loop, daemon=True)
        self._thread.start()
        self._consumer.start()
        # Eğer pencere takibi aktifse tracker'ı başlat
        if self._tracked_hwnd is not None:
            self._tracker = threading.Thread(target=self._track_window_loop, daemon=True)
            self._tracker.start()

    def stop(self) -> None:
        self.running = False
        self._tracked_hwnd = None   # takibi de durdur
        # Consumer'ı poison-pill ile sonlandır
        try:
            self._tq.put_nowait(None)
        except queue.Full:
            pass
        self._stab.reset()
        if self.overlay:
            self.overlay.destroy()
            self.overlay = None

    # ── Pencere Otomatik Takibi ────────────────────────────────────────────────
    def attach_window(self, hwnd: int, offset: Tuple[int, int, int, int]) -> None:
        """
        Belirli bir pencereyi (HWND) takip etmeye başla.
        offset: pencere sol-üst köşesine göre (x1, y1, x2, y2) göreli bölge.
        Kullanım: engine.attach_window(hwnd, (50, 800, 1870, 900))
        """
        self._tracked_hwnd    = hwnd
        self._region_offset   = offset

    def _track_window_loop(self) -> None:
        """
        Takip edilen pencerenin ekran konumunu her 500ms'de bir kontrol eder.
        Pencere taşındıysa region ve overlay pozisyonunu günceller.
        win32gui sadece burada kullanılır; kurulu değilse takip sessizce devre dışı kalır.
        """
        try:
            import ctypes
            user32 = ctypes.windll.user32  # type: ignore
        except Exception:
            return

        last_rect: Optional[Tuple] = None
        ox1, oy1, ox2, oy2 = self._region_offset or (0, 0, 0, 0)

        while self.running and self._tracked_hwnd is not None:
            try:
                hwnd = self._tracked_hwnd
                # GetWindowRect ile pencerenin ekran koordinatlarını al
                rect = ctypes.wintypes.RECT()  # type: ignore
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    wx, wy = rect.left, rect.top
                    new_rect = (wx, wy)
                    if new_rect != last_rect:
                        last_rect = new_rect
                        # Yeni bölge = pencere sol-üst + göreli offset
                        new_region = (
                            wx + ox1, wy + oy1,
                            wx + ox2, wy + oy2,
                        )
                        self.region = new_region
                        # mss mon dict'ini güncelle — Producer kendi döngüsünde okur
                        # Overlay konumunu da güncelle
                        if self.overlay and self.overlay.root.winfo_exists():
                            rx1, ry1, rx2, ry2 = new_region
                            gap  = 20
                            ov_h = 160
                            ny   = ry1 - ov_h - gap
                            if ny < 0:
                                ny = ry2 + gap
                            mid_x = rx1 + ((rx2 - rx1) // 2)
                            nx    = max(0, mid_x - (self.overlay.width // 2))
                            self.overlay._pos_x = nx
                            self.overlay._pos_y = ny
                            self.overlay.root.after(
                                0,
                                lambda _nx=nx, _ny=ny: self.overlay.root.geometry(
                                    f"+{_nx}+{_ny}"
                                ) if self.overlay and self.overlay.root.winfo_exists() else None,
                            )
            except Exception as exc:
                _log(f"[WindowTracker] {exc}", "WARN")
            time.sleep(0.5)

    # ── Yardımcı: Jaccard benzerliği ──────────────────────────────────────────
    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        sa = set(a.lower().split())
        sb = set(b.lower().split())
        if not sa and not sb:
            return 1.0
        u = len(sa | sb)
        return len(sa & sb) / u if u else 0.0

    # ── PRODUCER: OCR Tarama Döngüsü ──────────────────────────────────────────
    def _loop(self) -> None:
        global _active_ocr_engine

        if mss is None or np is None or cv2 is None:
            _log("[_loop KRITIK] mss / numpy / cv2 kurulu değil!", "CRITICAL")
            self.q.put({"a": "ocr", "t": "⚠ mss/cv2/numpy eksik — tam_kurulum.bat çalıştırın"})
            return
        if _active_ocr_engine is None:
            _log("[_loop KRITIK] OCR motoru henüz yüklenmedi, 3sn bekleniyor...", "WARN")
            time.sleep(3)
            if _active_ocr_engine is None:
                _log("[_loop KRITIK] OCR motoru hâlâ None — döngü başlamıyor!", "CRITICAL")
                self.q.put({"a": "ocr", "t": "⚠ OCR motoru yüklenemedi — app_log.txt inceleyin"})
                return

        _log(f"[Producer] Başladı. Bölge: {self.region}")
        empty           = 0
        last_txt        = ""
        last_fhash      = b""
        last_seen_text  = ""   # Jaccard dedup hafızası
        interval = max(0.05, self.app.get_interval())
        # Ultra modda (≤0.15s) stabilizer penceresi 3'e düşer → daha hızlı tepki
        stab_window = 3 if interval <= 0.15 else 6
        self._stab = TextStabilizer(window=stab_window, threshold=0.50)
        _log(f"[Producer] interval={interval:.2f}s  stab_window={stab_window}")
        if not self.region:
            return

        # Dil değişimi takibi için başlangıç hafızası
        last_src = LANGUAGES.get(self.app.src_lang_var.get(), "auto")
        last_tgt = TARGET_LANGS.get(self.app.tgt_lang_var.get(), "tr")

        with mss.mss() as sct:
            while self.running:
                try:
                    # ── CANLI AYAR GÜNCELLEMELERİ ──
                    # Hız (interval) ve Diller sürekli olarak güncel arayüzden çekilir
                    interval = max(0.05, self.app.get_interval())
                    src = LANGUAGES.get(self.app.src_lang_var.get(), "auto")
                    tgt = TARGET_LANGS.get(self.app.tgt_lang_var.get(), "tr")

                    # mon her frame'de self.region'dan oluşturulur
                    # Pencere takibi aktifse _track_window_loop bölgeyi günceller
                    if self.region:
                        mon = {
                            "left":   int(self.region[0]), "top":    int(self.region[1]),
                            "width":  int(self.region[2] - self.region[0]),
                            "height": int(self.region[3] - self.region[1]),
                        }

                    # Eğer kullanıcı dili anlık değiştirdiyse (Swap vb.) önbelleği silip o anki metni yeni dile zorla
                    if src != last_src or tgt != last_tgt:
                        last_seen_text = ""
                        last_fhash = b""
                        with self._cache._lock:
                            self._cache._d.clear()  # Geçmiş çeviri hafızasını sıfırla
                        last_src = src
                        last_tgt = tgt
                    # ───────────────────────────────

                    ov = self.overlay
                    if ov: ov.temp_hide()
                    frame = np.array(sct.grab(mon))
                    if ov: ov.temp_show()

                    fhash = cv2.resize(
                        frame, (32, 16), interpolation=cv2.INTER_NEAREST
                    ).tobytes()

                    # ── Kare aynı → Stabilizer'a tekrar besle ─────────────
                    if fhash == last_fhash:
                        if last_txt and len(last_txt) >= 2:
                            stable = self._stab.push(last_txt)
                            if stable:
                                cached = self._cache.get(stable)
                                if cached:
                                    self.q.put({"a": "waterfall", "t": cached})
                                    self.q.put({"a": "tr",        "t": cached})
                                else:
                                    self._enqueue_translation(
                                        stable, src, tgt, last_seen_text
                                    )
                                    last_seen_text = stable
                        time.sleep(interval)
                        continue
                    last_fhash = fhash

                    enhanced, px = OCRProcessor.process(frame)

                    if px < 20:
                        empty += 1
                        if empty >= 5:
                            self.q.put({"a": "hide"})
                            last_txt = ""; last_fhash = b""
                        time.sleep(interval)
                        continue

                    eng = _active_ocr_engine
                    raw = eng.read(enhanced) if eng else []
                    txt = self._clean(self._build_lines(raw))
                    last_txt = txt
                    self.q.put({"a": "ocr", "t": txt})

                    stable = self._stab.push(txt)
                    if stable and len(stable) >= 2:
                        empty = 0
                        cached = self._cache.get(stable)
                        if cached:
                            # Cache hit — doğrudan waterfall'a gönder ve geçmişe ekle
                            self.q.put({"a": "waterfall", "t": cached})
                            self.q.put({"a": "tr",        "t": cached})
                            self.app.root.after(0, lambda t=cached: self.app._add_to_history(t))
                        else:
                            # ── Jaccard Dedup (%40 barajı) ────────────────
                            sim = self._jaccard(stable, last_seen_text)
                            if sim < self.DEDUP_THRESHOLD:
                                # Diyalog değişti → kuyruğa at
                                last_seen_text = stable
                                try:
                                    self._tq.put_nowait((stable, src, tgt, time.monotonic()))
                                except queue.Full:
                                    try:
                                        self._tq.get_nowait()
                                    except queue.Empty:
                                        pass
                                    try:
                                        self._tq.put_nowait((stable, src, tgt, time.monotonic()))
                                    except queue.Full:
                                        pass
                    elif txt and len(txt) >= 2:
                        empty = 0
                    else:
                        empty += 1
                        if empty >= 5:
                            self.q.put({"a": "hide"})
                            last_fhash = b""
                            self._stab.reset()

                except Exception as exc:
                    _log(f"[Producer Hatası] {exc}\n{traceback.format_exc()}", "ERROR")
                time.sleep(interval)

    def _enqueue_translation(
        self, txt: str, src: str, tgt: str, last_seen: str
    ) -> None:
        """Stabilizer cache-miss: Jaccard kontrolü yaparak kuyruğa ekle."""
        sim = self._jaccard(txt, last_seen)
        if sim < self.DEDUP_THRESHOLD:
            try:
                self._tq.put_nowait((txt, src, tgt, time.monotonic()))
            except queue.Full:
                pass

    # ── CONSUMER: Çeviri İşçisi ───────────────────────────────────────────────
    def _consumer_loop(self) -> None:
        _log("[Consumer] Başladı.")
        while True:
            try:
                item = self._tq.get(block=True, timeout=1.0)
            except queue.Empty:
                if not self.running:
                    break
                continue

            if item is None:           # poison-pill → durdur
                _log("[Consumer] Poison-pill alındı, durduruluyor.")
                break

            txt, src, tgt, enqueued_time = item
            try:
                elapsed = time.monotonic() - enqueued_time
                if elapsed >= 4.0:
                    self._cache.put(txt, txt)  # sadece cache'e yaz, gösterme
                    continue
                prefixes, dialogs = self._split_speaker(txt)
                dialog_text = "\n".join(dialogs)
                
                # Sabit Google yerine, akıllı TranslationEngine'i kullanıyoruz!
                result, used_eng = self.app.translator.translate(dialog_text, src, tgt)
                
                tr_lines = result.split("\n") if result else dialogs
                tr = "\n".join(
                    (prefixes[i] if i < len(prefixes) else "") + t
                    for i, t in enumerate(tr_lines)
                )
                self._cache.put(txt, tr)
                self.q.put({"a": "waterfall", "t": tr})
                self.q.put({"a": "tr",        "t": tr, "e": used_eng}) # Hangi motorun çalıştığını UI'a gönder
                self.app.root.after(0, lambda t=tr: self.app._add_to_history(t))
            except Exception as exc:
                _log(f"[Consumer Çeviri Hatası] {exc}\n{traceback.format_exc()}", "ERROR")
            finally:
                self._tq.task_done()

        _log("[Consumer] Döngü tamamlandı.")

    # ── Statik yardımcılar ────────────────────────────────────────────────────
    @staticmethod
    def _build_lines(ocr_result: Any, gap: int = 15) -> str:
        if not ocr_result:
            return ""
        items = sorted(
            [((b[0][1] + b[1][1]) / 2, t) for b, t, _ in ocr_result],
            key=lambda x: x[0],
        )
        lines: List[str] = []
        cur_y, cur_words = items[0][0], [items[0][1]]
        for y, word in items[1:]:
            if abs(y - cur_y) <= gap:
                cur_words.append(word)
            else:
                lines.append(" ".join(cur_words))
                cur_y, cur_words = y, [word]
        lines.append(" ".join(cur_words))
        return "\n".join(lines)

    @staticmethod
    def _clean(t: str) -> str:
        if not t:
            return ""
        raw = t.strip()
        if len(raw) < 12:
            return raw
        out: List[str] = []
        for line in t.split("\n"):
            line = " ".join(re.sub(r"[^\w\s'\".,!?;:\-()\&]", "", line).split())
            if not line:
                continue
            words  = line.split()
            long_w = [w for w in words if len(re.sub(r"[^a-zA-Z]", "", w)) >= 5]
            noisy  = 0
            for w in long_w:
                lat = re.sub(r"[^a-zA-Z]", "", w)
                if lat and len(re.findall(r"[aeiouAEIOU]", lat)) / len(lat) <= 0.22:
                    noisy += 1
            if long_w and noisy / len(long_w) > 0.40:
                continue
            out.append(line)
        return "\n".join(out)

    @staticmethod
    def _split_speaker(txt: str) -> Tuple[List[str], List[str]]:
        prefixes: List[str] = []; dialogs: List[str] = []
        for line in txt.split("\n"):
            m = re.match(r"^([A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğışöü\s]{0,25}):\s*(.+)", line)
            if m:
                prefixes.append(m.group(1) + ": ")
                dialogs.append(m.group(2))
            else:
                prefixes.append("")
                dialogs.append(line)
        return prefixes, dialogs


# ═══════════════════════════════════════════════════════════════════════════════
# GÖREV PANELİ (UI Bileşeni)
# ═══════════════════════════════════════════════════════════════════════════════

class TaskPanel(ctk.CTkFrame):
    """Tek bir tarama görevi için UI kartı (Altyazı veya HUD)."""

    STATUS_IDLE    = ("⬛", "#6E7681")
    STATUS_ACTIVE  = ("🟢", "#7EE787")
    STATUS_REGION  = ("📍", "#D29922")

    def __init__(self, parent: Any, name: str, icon: str, app: "App"):
        super().__init__(
            parent,
            fg_color=("white", "#13161F"),
            corner_radius=14,
            border_width=1,
            border_color=("gray80", "#2D3348"),
        )
        self.name = name
        self.icon = icon
        self.app  = app
        self.engine = TaskEngine(app)
        self._build()
        self._poll()

    def _build(self) -> None:
        # ── Başlık ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(hdr, text=f"{self.icon}  {self.name}",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        self._dot = ctk.CTkLabel(hdr, text="⬛", width=24, text_color="#6E7681")
        self._dot.pack(side="right")

        # ── Uyarı — şerit/arka plan önerisi ─────────────────────────────────
        warn = ctk.CTkLabel(
            self,
            text="⚠ En iyi sonuç için oyun altyazı ayarlarından metin arka şeridini (background strip) açın.",
            font=ctk.CTkFont(size=10),
            text_color="#D29922",
            wraplength=370,
            justify="left",
        )
        warn.pack(anchor="w", padx=14, pady=(0, 4))
        
        # ── Dil Yönü (Altyazı Paneli İçi) ───────────────────────────────────
        # DÜZELTME: pack() ve grid() geometri yöneticilerini karıştırma
        lang_row = ctk.CTkFrame(self, fg_color="transparent")
        lang_row.pack(fill="x", padx=14, pady=(6, 8))
        lang_row.pack_propagate(True)
        
        # İç çerçeve: grid öğeleri için
        lang_inner = ctk.CTkFrame(lang_row, fg_color="transparent")
        lang_inner.pack(fill="x")
        lang_inner.grid_columnconfigure(0, weight=1)
        lang_inner.grid_columnconfigure(1, weight=0)
        lang_inner.grid_columnconfigure(2, weight=1)

        # Hatalı olan ComboBox yerine stabil olan OptionMenu kullanıyoruz
        src_menu = ctk.CTkOptionMenu(
            lang_inner, variable=self.app.src_lang_var, values=list(LANGUAGES.keys()),
            fg_color=("gray88", "#161924"), button_color=("gray80", "#21262D"),
            button_hover_color=("gray70", "#30363D"), text_color=("gray20", "#C9D1D9"),
            font=ctk.CTkFont(size=12), dropdown_font=ctk.CTkFont(size=12), height=28
        )
        src_menu.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        def _swap_langs():
            s = self.app.src_lang_var.get()
            t = self.app.tgt_lang_var.get()
            # Otomatik dili yer değiştirmeyi engelle, diğer her şeyi çevir
            if s != "Otomatik" and t in LANGUAGES and s in TARGET_LANGS:
                self.app.src_lang_var.set(t)
                self.app.tgt_lang_var.set(s)

        swap_btn = ctk.CTkButton(
            lang_inner, text="⇄", width=30, height=28, fg_color="transparent",
            hover_color=("gray80", "#21262D"), text_color="#58A6FF",
            font=ctk.CTkFont(size=16, weight="bold"), command=_swap_langs
        )
        swap_btn.grid(row=0, column=1)

        tgt_menu = ctk.CTkOptionMenu(
            lang_inner, variable=self.app.tgt_lang_var, values=list(TARGET_LANGS.keys()),
            fg_color=("gray88", "#161924"), button_color=("gray80", "#21262D"),
            button_hover_color=("gray70", "#30363D"), text_color=("gray20", "#C9D1D9"),
            font=ctk.CTkFont(size=12), dropdown_font=ctk.CTkFont(size=12), height=28
        )
        tgt_menu.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        # ── Bölge bilgisi ────────────────────────────────────────────────────
        self._region_lbl = ctk.CTkLabel(
            self, text="Henüz seçilmedi",
            font=ctk.CTkFont(size=11), text_color=("gray50", "#8B949E"),
        )
        self._region_lbl.pack(anchor="w", padx=16, pady=(0, 4))

        # ── Butonlar ─────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 8))

        self._sel_btn = ctk.CTkButton(
            btn_row, text="📍 Bölge Seç", width=108, height=30,
            fg_color=("#238636", "#238636"), hover_color="#1E7A30",
            command=self.select_region,
        )
        self._sel_btn.pack(side="left", padx=(0, 8))

        self._start_btn = ctk.CTkButton(
            btn_row, text="▶ Başlat", width=108, height=30,
            fg_color=("#1F6FEB", "#1F6FEB"), hover_color="#1A5FCC",
            state="disabled", command=self.toggle,
        )
        self._start_btn.pack(side="left")

        # Pencere Takibi butonu
        self._track_btn = ctk.CTkButton(
            btn_row, text="🎯 Pencere Takip", width=124, height=30,
            fg_color=("gray70", "#2D3348"), hover_color=("gray60", "#3D4560"),
            text_color=("gray20", "#C9D1D9"),
            command=self.pick_tracked_window,
        )
        self._track_btn.pack(side="left", padx=(8, 0))

        # ── Önizleme kutusu ──────────────────────────────────────────────────
        box = ctk.CTkFrame(self, fg_color=("gray92", "#0D1117"), corner_radius=10)
        box.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        self._ocr_lbl = ctk.CTkLabel(
            box, text="OCR: —", font=ctk.CTkFont(size=11),
            text_color=("gray50", "#8B949E"), anchor="w", wraplength=380,
        )
        self._ocr_lbl.pack(fill="x", padx=12, pady=(8, 2))

        self._tr_lbl = ctk.CTkLabel(
            box, text="TR: —", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1A8F3C", "#7EE787"), anchor="w", wraplength=380,
        )
        self._tr_lbl.pack(fill="x", padx=12, pady=(2, 10))

    # ── Kuyruk Polling ───────────────────────────────────────────────────────
    def _poll(self) -> None:
        try:
            while True:
                msg = self.engine.q.get_nowait()
                a = msg.get("a")
                t = str(msg.get("t", ""))
                if a == "waterfall":
                    # Consumer'dan gelen tamamlanmış çeviri → Waterfall overlay'e
                    if self.engine.overlay:
                        self.engine.overlay.push_line(t)
                elif a == "show":
                    # LRU cache hit — geriye dönük uyumluluk
                    if self.engine.overlay:
                        self.engine.overlay.push_line(t)
                elif a == "hide":
                    if self.engine.overlay:
                        self.engine.overlay.hide()
                elif a == "ocr":
                    self._ocr_lbl.configure(
                        text="OCR: " + (t[:65] + "…" if len(t) > 65 else t or "—"))
                elif a == "tr":
                    self._tr_lbl.configure(
                        text="TR: "  + (t[:65] + "…" if len(t) > 65 else t or "—"))
                    # Motor ping efektini tetikle
                    used_engine = msg.get("e")
                    if used_engine:
                        self.app.ping_translation_engine(used_engine)
        except queue.Empty:
            pass
        self.after(33, self._poll)

    # ── Kontroller ────────────────────────────────────────────────────────────
    def select_region(self) -> None:
        if self.engine.running:
            self.stop()
        self.app.root.withdraw()
        self.app.root.after(180, lambda: RegionSelector(self._on_region))

    def _on_region(self, r: Optional[Tuple]) -> None:
        self.app.root.deiconify()
        if r:
            self.engine.region = r
            w, h = r[2] - r[0], r[3] - r[1]
            self._region_lbl.configure(
                text=f"✓  {w} × {h} piksel", text_color="#7EE787"
            )
            self._start_btn.configure(state="normal")
            self._dot.configure(text="📍", text_color="#D29922")
    def toggle(self) -> None:
        if self.engine.running:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if not self.engine.region:
            return
        self.engine.start()
        self._start_btn.configure(
            text="⬛ Durdur", fg_color="#DA3633", hover_color="#B62D2A"
        )
        self._sel_btn.configure(state="disabled")
        self._track_btn.configure(state="disabled")
        self._dot.configure(text="🟢", text_color="#7EE787")
        self.app._refresh_glow()

    def stop(self) -> None:
        self.engine.stop()
        self._start_btn.configure(
            text="▶ Başlat", fg_color="#1F6FEB", hover_color="#1A5FCC"
        )
        self._sel_btn.configure(state="normal")
        self._track_btn.configure(state="normal")
        self._dot.configure(text="⬛", text_color="#6E7681")
        self.app._refresh_glow()

    def pick_tracked_window(self) -> None:
        """
        Kullanıcıya açık pencereleri listele; seçilen pencereyi takip et.
        Pencere takibi aktifken bölge seçiciye gerek kalmaz — offset mevcut
        region'dan hesaplanır ya da sıfırdan başlatılır.
        win32gui kurulu değilse butonu devre dışı bırakır ve uyarı gösterir.
        """
        try:
            import ctypes
            import ctypes.wintypes
        except ImportError:
            self._track_btn.configure(text="🎯 Takip (ctypes yok)", state="disabled")
            return

        user32 = ctypes.windll.user32  # type: ignore

        # Görünür, başlıklı pencereleri topla
        windows: List[Tuple[int, str]] = []

        def _enum_cb(hwnd: int, _: Any) -> bool:
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                title = buf.value.strip()
                if title and title not in ("Program Manager", ""):
                    windows.append((hwnd, title))
            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)

        if not windows:
            return

        # Seçim penceresi
        picker = _tk.Toplevel()
        picker.title("Takip Edilecek Pencereyi Seç")
        picker.geometry("540x400")
        picker.grab_set()
        picker.focus_force()

        _tk.Label(picker, text="Takip edilecek pencereyi seçin:", font=("Segoe UI", 11)).pack(pady=(12, 4))

        lb_frame = _tk.Frame(picker)
        lb_frame.pack(fill=_tk.BOTH, expand=True, padx=12, pady=4)
        scrollbar = _tk.Scrollbar(lb_frame)
        scrollbar.pack(side=_tk.RIGHT, fill=_tk.Y)
        lb = _tk.Listbox(lb_frame, yscrollcommand=scrollbar.set, font=("Segoe UI", 10),
                         selectmode=_tk.SINGLE, activestyle="none")
        lb.pack(fill=_tk.BOTH, expand=True)
        scrollbar.config(command=lb.yview)
        for _, title in windows:
            lb.insert(_tk.END, title)
        if windows:
            lb.selection_set(0)

        info_lbl = _tk.Label(picker, text="Bölge seçimi gerekmez — mevcut bölge ofset olarak kullanılır.",
                             font=("Segoe UI", 9), fg="gray")
        info_lbl.pack(pady=(2, 0))

        def _confirm() -> None:
            sel = lb.curselection()
            if not sel:
                return
            hwnd, title = windows[sel[0]]
            # Mevcut region'u pencerenin anlık konumuna göre ofset olarak hesapla
            rect = ctypes.wintypes.RECT()
            if self.engine.region and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                wx, wy = rect.left, rect.top
                rx1, ry1, rx2, ry2 = self.engine.region
                offset = (rx1 - wx, ry1 - wy, rx2 - wx, ry2 - wy)
            else:
                offset = (0, 0, 400, 100)   # fallback: pencerenin sol-üst köşesi
            self.engine.attach_window(hwnd, offset)
            self._track_btn.configure(
                text=f"🎯 {title[:22]}…" if len(title) > 22 else f"🎯 {title}",
                fg_color=("#1E7A30", "#238636"),
            )
            self._region_lbl.configure(
                text=f"📡 Takip: {title[:30]}", text_color="#7EE787"
            )
            self._start_btn.configure(state="normal")
            picker.destroy()

        def _cancel() -> None:
            picker.destroy()

        btn_row = _tk.Frame(picker)
        btn_row.pack(pady=8)
        _tk.Button(btn_row, text="Seç ve Başlat", command=_confirm,
                   font=("Segoe UI", 10), padx=16, pady=4).pack(side=_tk.LEFT, padx=6)
        _tk.Button(btn_row, text="İptal", command=_cancel,
                   font=("Segoe UI", 10), padx=16, pady=4).pack(side=_tk.LEFT, padx=6)
        lb.bind("<Double-Button-1>", lambda _e: _confirm())

# ═══════════════════════════════════════════════════════════════════════════════
# TOOLTIP (Bilgi Kutucuğu) Sınıfı
# ═══════════════════════════════════════════════════════════════════════════════
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.tw = _tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = _tk.Label(self.tw, text=self.text, justify="left",
                          background="#1A1F2E", foreground="#E6EDF3",
                          relief="solid", borderwidth=1,
                          font=("Segoe UI", 10), padx=8, pady=6)
        label.pack()

    def leave(self, event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None
# ═══════════════════════════════════════════════════════════════════════════════
# ANA UYGULAMA
# ═══════════════════════════════════════════════════════════════════════════════

class App:

    # ── Motor kartı meta-verileri ─────────────────────────────────────────────
    ENGINE_META = {
        "standard": {
            "label":  "Windows OCR",
            "icon":   "💨",
            "desc":   "Hizli & Hafif\nKurulum gerektirmez\nDüşük RAM kullanımı",
            "req":    "Windows 10/11 yeterli",
            "action": "winrt",
            "load":   "★ CPU %1–2 │ RAM ~50 MB",
            "net":    "✅ İnternet gerekmez",
            "needs":  "Windows 10/11 (yerleşik WinRT API)",
            "pros":   "⚡ Anında başlar, sıfır kurulum, düşük ısı",
            "cons":   "⚠ Karmaşık / elle yazı fontlarında yanlış okuyabilir",
        },
        "advanced": {
            "label":  "EasyOCR GPU",
            "icon":   "⚡",
            "desc":   "Yüksek doğruluk\nNVIDIA GPU gerekli\nGrafik metin desteği",
            "req":    "~2.5 GB VRAM + ~700 MB disk",
            "action": "easyocr",
            "load":   "★★★ GPU %40–80 │ VRAM ~1.5 GB",
            "net":    "📥 Kurulumda ~2.5 GB indirir",
            "needs":  "NVIDIA GPU + CUDA 11.8+ + Python 3.9+",
            "pros":   "🎯 En yüksek OCR doğruluğu, süslü fontlar",
            "cons":   "⚠ Yüksek VRAM, ilk yükleme ~20s sürebilir",
        },
        "hybrid": {
            "label":  "Hibrit OCR",
            "icon":   "🔀",
            "desc":   "Akıllı motor seçimi\nWinOCR + EasyOCR birleşimi\nKalite bazlı karar",
            "req":    "Ek kurulum gerekmez",
            "action": "hybrid",
            "load":   "★–★★ Moda bağlı │ RAM 50–1500 MB",
            "net":    "✅ İnternet gerekmez",
            "needs":  "Windows 10/11 │ İsteğe bağlı NVIDIA GPU",
            "pros":   "🎯 WinOCR hızı + EasyOCR doğruluğu, otomatik denge",
            "cons":   "⚠ Agresif modda EasyOCR/GPU VRAM gerekir",
        },
    }

    def __init__(self):
        # ── WINDOWS GÖREV ÇUBUĞU VE SİMGE AYARLARI ──
        try:
            # Windows'a bunun standart bir Python betiği değil, bağımsız bir uygulama olduğunu söyler
            import ctypes
            myappid = 'TercumanV1.0'  # Benzersiz bir uygulama kimliği
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(f"🎮 Tercüman {APP_VERSION}")
        
        # Hazırladığımız icon.ico dosyasını Görev Çubuğuna ve pencereye uygula
        icon_path = os.path.join(BASE_DIR, "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self.root.geometry("1180x800")
        self.root.resizable(False, False)  # Sabit boyut

        # Değişkenler
        self.src_lang_var   = ctk.StringVar(value="İngilizce (EN)")
        self.tgt_lang_var   = ctk.StringVar(value="Türkçe (TR)")
        self.interval_var   = ctk.StringVar(value="0.5")
        self.font_size_var  = ctk.IntVar(value=18)
        self.font_color_var = ctk.StringVar(value="Beyaz")
        self.font_family_var= ctk.StringVar(value="Segoe UI")
        self.font_bold_var  = ctk.BooleanVar(value=True)
        self.engine_var     = ctk.StringVar(value="standard")
        self.hybrid_mode_var= ctk.StringVar(value="standard")  # "standard" | "aggressive"

        # ── YENİ: Çeviri motoru ──────────────────────────────────────────────
        self.translation_engine_var = ctk.StringVar(value="google")   # google|gemini
        self.gemini_key_var         = ctk.StringVar(value="")
        
        # Çeviri motorunu başlat ve UI referanslarını ayarla
        self.translator = TranslationEngine(self)
        self._trans_desc_lbl: Optional[Any] = None

        # ── YENİ: OCR hassasiyet parametreleri ──────────────────────────────
        self.ocr_quality_thresh_var = ctk.StringVar(value="40")   # HybridOCR quality threshold
        self.ocr_stab_window_var    = ctk.StringVar(value="6")    # TextStabilizer window
        self.ocr_stab_thresh_var    = ctk.StringVar(value="0.50") # TextStabilizer Jaccard threshold

        # Kurulum iptal/geri alma mekanizması
        self._install_stop  = threading.Event()   # İptal sinyali
        self._install_proc: Optional[Any] = None  # Aktif subprocess
        self._installed_pkgs: List[str] = []      # Bu oturumda kurulanlar

        # UI ölçeği ve tema
        self._ui_scale_var  = ctk.StringVar(value="1.0")
        self._dark_mode     = True

        # Çeviri geçmişi (tekilleştirilmiş, son 30)
        from collections import deque
        self._tr_history: deque = deque(maxlen=30)
        self._tr_history_seen: set = set()
        self._hist_labels: list = []

        self._load_settings()
        self._build_ui()
        self._setup_hotkeys()
        self._init_ocr()
        
        # Eğer daha önceden kaydedilmiş bir Gemini API anahtarı varsa açılışta sessizce test et
        if self.gemini_key_var.get().strip():
            self._test_gemini_key()
            
        # Ana ekranı göstermeden önce Rastgele Logolu Açılışı başlat
        self._show_splash()

    # ── Yardımcı getter'lar ──────────────────────────────────────────────────
    def get_interval(self) -> float:
        try:
            return float(self.interval_var.get())
        except Exception:
            return 0.5

    def get_overlay_config(self) -> Dict[str, Any]:
        color_hex = FONT_COLORS.get(self.font_color_var.get(), "#FFFFFF")
        return {
            "font_size":   self.font_size_var.get(),
            "font_family": self.font_family_var.get(),
            "font_color":  color_hex,
            "font_bold":   self.font_bold_var.get(),
        }

    # ── UI İnşası ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)  # Sidebar kaldırıldı — main başlıyor col 0
        self.root.grid_rowconfigure(0, weight=1)

        self._build_main()

    # ── Sol Kenar Çubuğu ─────────────────────────────────────────────────────
# ── Ana Alan ─────────────────────────────────────────────────────────────
    def _build_main(self) -> None:
        main = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        main.grid(row=0, column=0, sticky="nsew")  # ← Sidebar kaldırıldı, col=0
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)  # 3-sütun grid için başlık

        # Üst başlık (hdr BURADA tanımlanıyor)
        hdr = ctk.CTkFrame(main, height=68, corner_radius=0,
                           fg_color=("white", "#161B22"))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🎮  OYUN ÇEVİRİ MOTORU",
                     font=ctk.CTkFont(size=21, weight="bold"),
                     text_color=("gray20", "#58A6FF")).pack(side="left", padx=24, pady=14)

        # ── Arayüz Ölçeği (Üst Çubuk) ───────────────────────────────────────
        scale_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        scale_frame.pack(side="left", padx=(10, 0), pady=14)
        
        ctk.CTkLabel(scale_frame, text="🔍 Ölçek:", font=ctk.CTkFont(size=11), text_color="gray50").pack(side="left", padx=(0, 6))
        
        # Üst çubuğa sığması için butonları biraz daha minimal yaptık (S, M, L, XL)
        UI_SCALES = [("S", "0.85"), ("M", "1.0"), ("L", "1.15"), ("XL", "1.35")]
        self._scale_btns: dict = {}
        for lbl, val in UI_SCALES:
            b = ctk.CTkButton(
                scale_frame, text=lbl, width=32, height=26,
                fg_color=("#1F6FEB" if getattr(self, "_ui_scale_var", ctk.StringVar(value="1.0")).get() == val else "gray30"),
                corner_radius=6,
                command=lambda v=val: self._pick_ui_scale(v)
            )
            b.pack(side="left", padx=2)
            self._scale_btns[val] = b
        # ──────────────────────────────────────────────────────────────────

        # Tema Toggle
        self._theme_btn = ctk.CTkButton(
            hdr, text="🌙 Koyu", width=72, height=30,
            fg_color="transparent", border_width=1,
            border_color=("gray75", "#30363D"),
            text_color=("gray40", "gray70"),
            font=ctk.CTkFont(size=10),
            command=self._toggle_theme,
        )
        self._theme_btn.pack(side="right", padx=(0, 12), pady=14)

        self._ocr_status = ctk.CTkLabel(
            hdr, text="🔍 Donanım Taranıyor...",
            font=ctk.CTkFont(size=11), text_color="#D29922",
        )
        self._ocr_status.pack(side="right", padx=8)

        # Motor seçimi değişince durum etiketini güncelle
        def _on_engine_change(*_: Any) -> None:
            labels = {
                "standard": "💨 Windows OCR",
                "advanced": "⚡ EasyOCR GPU",
                "hybrid":   "🔀 Hibrit OCR",
            }
            sel_key = self.engine_var.get()
            sel     = labels.get(sel_key, "")
            if not sel:
                return
            installed = self._check_installed(sel_key)
            # Motor değişince eski hw_suffix geçersiz — sıfırla
            self._hw_suffix = ""
            if installed:
                txt   = f"{sel} — Hazır"
                color = "#7EE787"
            else:
                txt   = f"⚠ {sel} — Kurulmadı (Windows OCR aktif)"
                color = "#DA3633"
            self._ocr_status.configure(text=txt, text_color=color)
        self.engine_var.trace_add("write", _on_engine_change)

        # Kaydırılabilir içerik — 3-SÜTUNLU LAYOUT
        scroll = ctk.CTkScrollableFrame(
            main, fg_color="transparent",
            scrollbar_button_color=("gray85", "#242424"),
            scrollbar_button_hover_color=("gray85", "#242424")
        )
        scroll.pack(fill="both", expand=True, padx=22, pady=12)
        scroll.grid_columnconfigure((0, 1, 2), weight=1)  # 3-SÜTUNLU LAYOUT

        # ── Görev kartı ve Altyazı Ayarları (yan yana) ─────────────────────
        self.panel_sub = TaskPanel(scroll, "ALTYAZI", "🎬", self)
        self.panel_sub.grid(row=0, column=0, padx=(0, 8), pady=(0, 12), sticky="nsew")

        # ── Yeni Altyazı Stil Kartı (Sağ Taraf) ────────────────────────────
        style_card = ctk.CTkFrame(scroll, fg_color=("white", "#13161F"),
                                  corner_radius=14, border_width=1,
                                  border_color=("gray80", "#30363D"))
        style_card.grid(row=0, column=1, padx=(8, 0), pady=(0, 12), sticky="nsew")

        hdr_style = ctk.CTkFrame(style_card, fg_color="transparent")
        hdr_style.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(hdr_style, text="🎨  ALTYAZI GÖRÜNÜMÜ", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

        ov = ctk.CTkFrame(style_card, fg_color="transparent")
        ov.pack(fill="both", expand=True, padx=14, pady=(4, 12))
        ov.grid_columnconfigure(1, weight=1)

        # Yazı Tipi
        ctk.CTkLabel(ov, text="Yazı Tipi:", font=ctk.CTkFont(size=11), text_color="gray50").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ctk.CTkComboBox(
            ov, variable=self.font_family_var,
            values=["Segoe UI", "Arial", "Consolas", "Trebuchet MS", "Verdana"],
            width=160, state="readonly", command=self._apply_style,
        ).grid(row=0, column=1, sticky="w", padx=10, pady=(0, 8))

        # Renk
        ctk.CTkLabel(ov, text="Renk:", font=ctk.CTkFont(size=13), text_color="gray50").grid(row=1, column=0, sticky="w", pady=(0, 8))
        clr_row = ctk.CTkFrame(ov, fg_color="transparent")
        clr_row.grid(row=1, column=1, sticky="w", padx=10, pady=(0, 8))
        self._color_btns: dict = {}
        for name, hex_c in FONT_COLORS.items():
            # Zemin rengine göre okunabilir metin rengini ayarla
            txt_clr = "black" if hex_c in ("#FFFFFF", "#FFD700", "#00FFFF", "#00FF88", "#FFA500", "#FF66FF") else "white"
            
            b = ctk.CTkButton(
                clr_row, text=name, width=50, height=26,
                fg_color=hex_c,                # Doğrudan rengin kendisi
                hover_color=hex_c,             # Üzerine gelince rengi solmasın
                text_color=txt_clr,            # Dinamik siyah/beyaz metin
                font=ctk.CTkFont(size=11, weight="bold"),
                corner_radius=8,               # Daha yumuşak köşeler
                command=lambda n=name: self._pick_color(n),
            )
            b.pack(side="left", padx=3)
            self._color_btns[name] = b
            # Döngü bittikten hemen sonra program açılışında kayıtlı rengi vurgula
        self._pick_color(self.font_color_var.get())

        # Boyut & Kalınlık
        ctk.CTkLabel(ov, text="Boyut:", font=ctk.CTkFont(size=11), text_color="gray50").grid(row=2, column=0, sticky="w", pady=(4, 0))
        sz_row = ctk.CTkFrame(ov, fg_color="transparent")
        sz_row.grid(row=2, column=1, sticky="w", padx=10, pady=(4, 0))
        
        self._size_lbl = ctk.CTkLabel(sz_row, textvariable=self.font_size_var, width=28, font=ctk.CTkFont(size=14, weight="bold"))
        self._size_lbl.pack(side="left", padx=(0, 8))
        ctk.CTkButton(sz_row, text="−", width=28, height=28, command=lambda: self._adj_size(-1)).pack(side="left", padx=2)
        ctk.CTkButton(sz_row, text="＋", width=28, height=28, command=lambda: self._adj_size(+1)).pack(side="left", padx=2)
        
        # Ön tanımlı boyutlar
        self._size_btns: dict = {}
        for lbl, sz in [("S", 14), ("M", 18), ("L", 24)]:
            b = ctk.CTkButton(
                sz_row, text=lbl, width=32, height=28,
                fg_color=("#1F6FEB" if self.font_size_var.get() == sz else "gray30"),
                corner_radius=6, command=lambda s=sz: self._pick_size_preset(s),
            )
            b.pack(side="left", padx=2)
            self._size_btns[sz] = b

        self._bold_btn = ctk.CTkButton(
            sz_row, text="B", width=32, height=28, font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1F6FEB" if self.font_bold_var.get() else "gray30", command=self._toggle_bold,
        )
        self._bold_btn.pack(side="left", padx=(8, 0))
        # ── Yeni Tarama Hızı (Slider) Alanı ────────────────────────────────
        sep = ctk.CTkFrame(style_card, height=1, fg_color=("gray80", "#2D3348"))
        sep.pack(fill="x", padx=14, pady=(8, 8))

        spd_row = ctk.CTkFrame(style_card, fg_color="transparent")
        spd_row.pack(fill="x", padx=14, pady=(0, 12))

        spd_hdr = ctk.CTkFrame(spd_row, fg_color="transparent")
        spd_hdr.pack(fill="x")
        
        ctk.CTkLabel(spd_hdr, text="⏱ Tarama Hızı:", font=ctk.CTkFont(size=11), text_color="gray50").pack(side="left")
        
        self.speed_display_lbl = ctk.CTkLabel(
            spd_hdr, text=f"{self.interval_var.get()} saniye", 
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#58A6FF"
        )
        self.speed_display_lbl.pack(side="right")

        def _on_slider_change(val):
            v = round(float(val), 2)
            self.interval_var.set(str(v))
            self.speed_display_lbl.configure(text=f"{v} saniye")

        slider = ctk.CTkSlider(
            spd_row, from_=0.1, to=3.0, number_of_steps=29, command=_on_slider_change
        )
        slider.set(float(self.interval_var.get()))
        slider.pack(fill="x", pady=(8, 0))

        # ── Çeviri Motoru (Translation Service) Kartı (Row 0, Col 2) ──────────────
        trans_card = ctk.CTkFrame(scroll, fg_color=("white", "#13161F"),
                                  corner_radius=14, border_width=1,
                                  border_color=("gray80", "#30363D"))
        trans_card.grid(row=0, column=2, padx=(8, 0), pady=(0, 12), sticky="nsew")

        # Header
        hdr_trans = ctk.CTkFrame(trans_card, fg_color="transparent")
        hdr_trans.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(hdr_trans, text="🌐  ÇEVİRİ MOTORU",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

        # Description (Durum Bildirici)
        self._trans_desc_lbl = ctk.CTkLabel(trans_card,
                                  text="Durum: Bekleniyor...",
                                  font=ctk.CTkFont(size=11, weight="bold"), text_color="gray50", justify="left")
        self._trans_desc_lbl.pack(fill="x", padx=14, pady=(0, 8))

        # Service selection buttons
        btn_frame = ctk.CTkFrame(trans_card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=14, pady=(0, 12))
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        TRANS_SERVICES = [("🔵 Google", "google"), ("🌟 Gemini AI", "gemini")]

        def _select_trans(service):
            self.translation_engine_var.set(service)

        self._trans_btns: dict = {}
        
        # 3 butonluk alanı 2 butona göre hizalayalım
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        btn_frame.grid_columnconfigure(2, weight=0) 
        
        for idx, (label, svc) in enumerate(TRANS_SERVICES):
            btn = ctk.CTkButton(
                btn_frame, text=label, height=32,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#238636" if self.translation_engine_var.get() == svc else "gray40",
                command=lambda s=svc: _select_trans(s),
            )
            btn.grid(row=0, column=idx, padx=4, sticky="ew")
            self._trans_btns[svc] = btn

        # Auto-save on translation engine change
        def _on_trans_change(*_):
            self._save_settings()
            current = self.translation_engine_var.get()
            for svc, btn in self._trans_btns.items():
                btn.configure(fg_color="#238636" if svc == current else "gray40")

        self.translation_engine_var.trace_add("write", _on_trans_change)

        # ── API KEY GİRİŞ ALANI VE LİNK ──
        import webbrowser
        api_frame = ctk.CTkFrame(trans_card, fg_color="transparent")
        api_frame.pack(fill="x", padx=14, pady=(0, 14))

        lbl_frame = ctk.CTkFrame(api_frame, fg_color="transparent")
        lbl_frame.pack(fill="x")
        
        info_lbl = ctk.CTkLabel(lbl_frame, text="Gemini API Key (Opsiyonel):", font=ctk.CTkFont(size=11), text_color="gray50")
        info_lbl.pack(side="left")
        
        # Yeni: Doğrulama Durum Etiketi
        self._api_status_lbl = ctk.CTkLabel(lbl_frame, text="", font=ctk.CTkFont(size=11, weight="bold"))
        self._api_status_lbl.pack(side="right", padx=(0, 10))

        # Tıklanabilir Mavi Link
        link_lbl = ctk.CTkLabel(lbl_frame, text="ℹ Ücretsiz Anahtar Al", font=ctk.CTkFont(size=11, underline=True), text_color="#58A6FF", cursor="hand2")
        link_lbl.pack(side="right")
        link_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://aistudio.google.com/app/apikey"))
        ToolTip(link_lbl, "Google AI Studio'ya gidip Google hesabınızla\ntek tıkla ücretsiz API anahtarı alabilirsiniz.\n(Boş bırakırsanız varsayılan Google kullanılır)")

        self.gemini_entry = ctk.CTkEntry(api_frame, textvariable=self.gemini_key_var, show="*", height=28, placeholder_text="AIzaSy...")
        self.gemini_entry.pack(fill="x", pady=(4, 8))
        
        # Enter'a basıldığında veya kutudan çıkıldığında doğrulamayı çalıştır
        self.gemini_entry.bind("<Return>", lambda e: self._test_gemini_key())
        self.gemini_entry.bind("<FocusOut>", lambda e: [self._save_settings(), self._test_gemini_key()])

       # ── Motor Seçimi (Animasyonlu Katlanabilir) ─────────────────────────
        eng_card = ctk.CTkFrame(scroll, fg_color=("white", "#13161F"),
                                corner_radius=14, border_width=1,
                                border_color=("gray80", "#30363D"))
        eng_card.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        # 1. Tıklanabilir Başlık Alanı
        eng_hdr = ctk.CTkFrame(eng_card, fg_color="transparent", cursor="hand2")
        eng_hdr.pack(fill="x", padx=14, pady=10)
        
        self.eng_arrow = ctk.CTkLabel(eng_hdr, text="▾", font=ctk.CTkFont(size=16), text_color=("gray50", "#8B949E"), width=20)
        self.eng_arrow.pack(side="left")
        
        eng_title = ctk.CTkLabel(eng_hdr, text="⚙  OCR MOTORU & ÇEVİRİ SİSTEMİ", font=ctk.CTkFont(size=13, weight="bold"), text_color=("gray40", "#58A6FF"))
        eng_title.pack(side="left", padx=4)

        # 2. İçerik Konteyneri (Animasyon için bu çerçevenin yüksekliğiyle oynayacağız)
        self.eng_content = ctk.CTkFrame(eng_card, fg_color="transparent")
        self.eng_content.pack(fill="x", padx=14, pady=(0, 14))
        
        # İçeriği barındıran asıl satır
        ec_row = ctk.CTkFrame(self.eng_content, fg_color="transparent")
        self._ec_row = ec_row  # _refresh_engine_cards için saklanıyor
        ec_row.pack(fill="x")
        ec_row.grid_columnconfigure((0, 1, 2), weight=1)

        self._eng_frames: dict = {}
        for col, (key, meta) in enumerate(self.ENGINE_META.items()):
            f = self._make_engine_card(ec_row, key, meta)
            f.grid(row=0, column=col, padx=5, sticky="nsew")
            self._eng_frames[key] = f

        # Progress bar ve Label artık eng_content'in içinde
        self._prog_bar = ctk.CTkProgressBar(self.eng_content, mode="determinate")
        self._prog_bar.set(0)
        self._prog_lbl = ctk.CTkLabel(self.eng_content, text="", font=ctk.CTkFont(size=11))

        self.engine_var.trace_add("write", lambda *_: self._refresh_glow())

        # 3. ── Animasyon Mantığı (60 FPS Smooth Slide) ──
        self._eng_open = True
        self._eng_animating = False

        def _toggle_eng(_e=None):
            if self._eng_animating:
                return
            self._eng_animating = True

            # Hedef yüksekliği belirle (İçerik ne kadar yer kaplıyorsa o kadar açılacak)
            target_h = ec_row.winfo_reqheight() + 10
            if self._prog_bar.winfo_ismapped():
                target_h += 50
                
            current_h = self.eng_content.winfo_height()
            
            # Dinamik paketlemeyi (pack) durdur, yüksekliğin kontrolünü ele al
            self.eng_content.pack_propagate(False)
            
            if self._eng_open:
                # Kapanma Modu
                self.eng_arrow.configure(text="▸")
                eng_title.configure(text_color=("gray50", "#8B949E"))
                step = -15 # Kapanma hızı
            else:
                # Açılma Modu
                self.eng_arrow.configure(text="▾")
                eng_title.configure(text_color=("gray40", "#58A6FF"))
                self.eng_content.pack(fill="x", padx=14, pady=(0, 14))
                step = 15  # Açılma hızı

            def animate():
                nonlocal current_h
                current_h += step
                
                # Sınır kontrolleri
                if (step < 0 and current_h <= 1) or (step > 0 and current_h >= target_h):
                    if step < 0:
                        # Tamamen kapandı
                        self.eng_content.configure(height=1)
                        self.eng_content.pack_forget()
                        self._eng_open = False
                    else:
                        # Tamamen açıldı, kontrolü tekrar arayüze (pack_propagate) bırak
                        self.eng_content.configure(height=target_h)
                        self.eng_content.pack_propagate(True) 
                        self._eng_open = True
                    self._eng_animating = False
                else:
                    # Bir sonraki kareyi (frame) çiz
                    self.eng_content.configure(height=current_h)
                    self.root.after(7, animate) # ~60fps hissiyatı için 12ms bekleme

            animate()

        # Fare tıklamasını hem başlığa hem oka bağla
        eng_hdr.bind("<Button-1>", _toggle_eng)
        self.eng_arrow.bind("<Button-1>", _toggle_eng)
        eng_title.bind("<Button-1>", _toggle_eng)
        # ────────────────────────────────────────────────────────────────────

# ── GELİŞMİŞ OKUMA AYARLARI Kartı (Row 2, Cols 0-2) ─────────────────
        ocr_sens_card = ctk.CTkFrame(scroll, fg_color=("white", "#13161F"),
                                     corner_radius=14, border_width=1,
                                     border_color=("gray80", "#30363D"))
        ocr_sens_card.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        # 1. Tıklanabilir Başlık Alanı
        hdr_ocr = ctk.CTkFrame(ocr_sens_card, fg_color="transparent", cursor="hand2")
        hdr_ocr.pack(fill="x", padx=14, pady=10)
        
        self.ocr_arrow = ctk.CTkLabel(hdr_ocr, text="▸", font=ctk.CTkFont(size=16), text_color=("gray50", "#8B949E"), width=20)
        self.ocr_arrow.pack(side="left")

        ocr_title = ctk.CTkLabel(hdr_ocr, text="🔬  GELİŞMİŞ OKUMA AYARLARI",
                                 font=ctk.CTkFont(size=13, weight="bold"), text_color=("gray50", "#8B949E"))
        ocr_title.pack(side="left", padx=4)

        # 2. İçerik Konteyneri (Animasyon için kapalı başlatıyoruz)
        self.ocr_anim_content = ctk.CTkFrame(ocr_sens_card, fg_color="transparent", height=1)
        self.ocr_anim_content.pack_propagate(False)

        # Description
        desc_ocr = ctk.CTkLabel(self.ocr_anim_content,
                               text="Çeviri hızı ve metin doğruluğu arasındaki dengeyi ince ayarlayın.",
                               font=ctk.CTkFont(size=11), text_color="gray50", justify="left")
        desc_ocr.pack(fill="x", padx=14, pady=(0, 8))

        # Content frame
        ocr_content = ctk.CTkFrame(self.ocr_anim_content, fg_color="transparent")
        ocr_content.pack(fill="both", expand=True, padx=14, pady=(4, 12))
        
        ocr_content.grid_columnconfigure(0, weight=1)
        ocr_content.grid_columnconfigure(1, weight=0)
        ocr_content.grid_columnconfigure(2, weight=0)

        # 3. ── Animasyon Mantığı (60 FPS Smooth Slide) ──
        self._ocr_open = False
        self._ocr_animating = False

        def _toggle_ocr(_e=None):
            if self._ocr_animating:
                return
            self._ocr_animating = True

            # Hedef yüksekliği otomatik hesapla
            target_h = ocr_content.winfo_reqheight() + desc_ocr.winfo_reqheight() + 35
            current_h = self.ocr_anim_content.winfo_height()
            self.ocr_anim_content.pack_propagate(False)

            if self._ocr_open:
                # Kapanma Modu
                self.ocr_arrow.configure(text="▸")
                ocr_title.configure(text_color=("gray50", "#8B949E"))
                step = -15
            else:
                # Açılma Modu
                self.ocr_arrow.configure(text="▾")
                ocr_title.configure(text_color=("gray40", "#58A6FF"))
                self.ocr_anim_content.pack(fill="x", padx=14, pady=(0, 14))
                step = 15

            def animate_ocr():
                nonlocal current_h
                current_h += step
                
                if (step < 0 and current_h <= 1) or (step > 0 and current_h >= target_h):
                    if step < 0:
                        self.ocr_anim_content.configure(height=1)
                        self.ocr_anim_content.pack_forget()
                        self._ocr_open = False
                    else:
                        self.ocr_anim_content.configure(height=target_h)
                        self.ocr_anim_content.pack_propagate(True)
                        self._ocr_open = True
                    self._ocr_animating = False
                else:
                    self.ocr_anim_content.configure(height=current_h)
                    self.root.after(7, animate_ocr)

            animate_ocr()

        # Fare tıklamasını bileşenlere bağla
        hdr_ocr.bind("<Button-1>", _toggle_ocr)
        self.ocr_arrow.bind("<Button-1>", _toggle_ocr)
        ocr_title.bind("<Button-1>", _toggle_ocr)

        # 1. Metin Netlik Sınırı
        lbl1 = ctk.CTkLabel(ocr_content, text="Metin Netlik Sınırı:", font=ctk.CTkFont(size=11), text_color="gray50")
        lbl1.grid(row=1, column=0, sticky="w", pady=(4, 0))
        
        info1 = ctk.CTkLabel(ocr_content, text="ℹ", font=ctk.CTkFont(size=12, weight="bold"), text_color="#58A6FF", cursor="question_arrow")
        info1.grid(row=1, column=1, padx=6, pady=(4, 0))
        ToolTip(info1, "Görüntü kalitesi bu puanın altına düşerse,\nsistem otomatik olarak güçlü (yedek) motora geçer.\n(Düşük: Nadiren geçer / Yüksek: Çabuk geçer)")

        qual_lbl = ctk.CTkLabel(ocr_content, textvariable=self.ocr_quality_thresh_var, font=ctk.CTkFont(size=11, weight="bold"))
        qual_lbl.grid(row=1, column=2, sticky="e", pady=(4, 0))

        def _on_qual_change(val):
            self.ocr_quality_thresh_var.set(str(int(float(val))))
            self._save_settings()

        self._qual_slider = ctk.CTkSlider(ocr_content, from_=30, to=50, number_of_steps=20, command=_on_qual_change)
        self._qual_slider.set(float(self.ocr_quality_thresh_var.get()))
        self._qual_slider.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        # 2. Titreşim Önleyici Hafıza
        lbl2 = ctk.CTkLabel(ocr_content, text="Titreşim Önleyici (Kare):", font=ctk.CTkFont(size=11), text_color="gray50")
        lbl2.grid(row=3, column=0, sticky="w", pady=(4, 0))
        
        info2 = ctk.CTkLabel(ocr_content, text="ℹ", font=ctk.CTkFont(size=12, weight="bold"), text_color="#58A6FF", cursor="question_arrow")
        info2.grid(row=3, column=1, padx=6, pady=(4, 0))
        ToolTip(info2, "Hızlı değişen veya titreyen yazıları sabitlemek\niçin hafızada tutulacak kare sayısını belirler.\n(Düşük: Hızlı tepki / Yüksek: Pürüzsüz yazı)")

        wind_lbl = ctk.CTkLabel(ocr_content, textvariable=self.ocr_stab_window_var, font=ctk.CTkFont(size=11, weight="bold"))
        wind_lbl.grid(row=3, column=2, sticky="e", pady=(4, 0))

        def _on_wind_change(val):
            self.ocr_stab_window_var.set(str(int(float(val))))
            self._save_settings()

        self._wind_slider = ctk.CTkSlider(ocr_content, from_=3, to=9, number_of_steps=6, command=_on_wind_change)
        self._wind_slider.set(float(self.ocr_stab_window_var.get()))
        self._wind_slider.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        # 3. Yeni Cümle Hassasiyeti
        lbl3 = ctk.CTkLabel(ocr_content, text="Yeni Cümle Hassasiyeti:", font=ctk.CTkFont(size=11), text_color="gray50")
        lbl3.grid(row=5, column=0, sticky="w", pady=(4, 0))

        info3 = ctk.CTkLabel(ocr_content, text="ℹ", font=ctk.CTkFont(size=12, weight="bold"), text_color="#58A6FF", cursor="question_arrow")
        info3.grid(row=5, column=1, padx=6, pady=(4, 0))
        ToolTip(info3, "Ekrana gelen metnin, öncekinden ne kadar\nfarklı olursa 'yeni bir çeviri' sayılacağını belirler.\n(Önerilen: 0.50)")

        jac_lbl = ctk.CTkLabel(ocr_content, textvariable=self.ocr_stab_thresh_var, font=ctk.CTkFont(size=11, weight="bold"))
        jac_lbl.grid(row=5, column=2, sticky="e", pady=(4, 0))

        def _on_jac_change(val):
            v = round(float(val), 2)
            self.ocr_stab_thresh_var.set(str(v))
            self._save_settings()

        self._jac_slider = ctk.CTkSlider(ocr_content, from_=0.30, to=0.70, number_of_steps=40, command=_on_jac_change)
        self._jac_slider.set(float(self.ocr_stab_thresh_var.get()))
        self._jac_slider.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(2, 0))

        # --- HAZIR AYARLAR (PRESETS) --- (KAYDIRMA ÇUBUKLARI OLUŞTUKTAN SONRA)
        preset_frame = ctk.CTkFrame(ocr_content, fg_color="transparent")
        preset_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        preset_frame.grid_columnconfigure((0, 1, 2), weight=1)

        def _set_preset(name, qual, wind, thresh):
            # 1. Arka plandaki sayısal değerleri kaydet
            self.ocr_quality_thresh_var.set(str(qual))
            self.ocr_stab_window_var.set(str(wind))
            self.ocr_stab_thresh_var.set(str(thresh))
            self._save_settings()
            
            # 2. Üstte oluşturduğumuz çubukları fiziksel olarak o noktaya it
            self._qual_slider.set(float(qual))
            self._wind_slider.set(float(wind))
            self._jac_slider.set(float(thresh))

        presets = [
            ("🎯 Sabit", 45, 3, "0.60"),
            ("⚖️ Dengeli", 40, 6, "0.50"),
            ("⚡ Hızlı", 35, 9, "0.30"),
        ]
        for idx, (name, q, w, t) in enumerate(presets):
            btn = ctk.CTkButton(
                preset_frame, text=name, height=28,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="gray40", hover_color="#238636",
                command=lambda qu=q, wi=w, th=t: _set_preset(name, qu, wi, th)
            )
            btn.grid(row=0, column=idx, padx=2, sticky="ew")
        # ────────────────────────────────────────────────────────────────────

        # ── Çeviri Geçmişi Paneli ──────────────────────────────────────────────
        hist_card = ctk.CTkFrame(scroll, fg_color=("white", "#13161F"),
                                 corner_radius=14, border_width=1,
                                 border_color=("gray80", "#30363D"))
        hist_card.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        # 1. Tıklanabilir Başlık Alanı
        hist_hdr = ctk.CTkFrame(hist_card, fg_color="transparent", cursor="hand2")
        hist_hdr.pack(fill="x", padx=14, pady=10)
        
        self.hist_arrow = ctk.CTkLabel(hist_hdr, text="▸", font=ctk.CTkFont(size=16), text_color=("gray50", "#8B949E"), width=20)
        self.hist_arrow.pack(side="left")

        hist_title = ctk.CTkLabel(hist_hdr, text="📜  ÇEVİRİ GEÇMİŞİ",
                                  font=ctk.CTkFont(size=13, weight="bold"), text_color=("gray50", "#8B949E"))
        hist_title.pack(side="left", padx=4)

        # Temizle butonu başlığın sağında dursun (tıklanması menüyü açıp kapatmaz)
        clear_btn = ctk.CTkButton(hist_hdr, text="🗑 Temizle", width=80, height=26,
                      fg_color="transparent", border_width=1,
                      border_color=("gray75", "#30363D"), text_color="gray60",
                      font=ctk.CTkFont(size=10),
                      command=self._clear_history)
        clear_btn.pack(side="right")

        # 2. İçerik Konteyneri (Animasyon için kapalı başlatıyoruz)
        self.hist_anim_content = ctk.CTkFrame(hist_card, fg_color="transparent", height=1)
        self.hist_anim_content.pack_propagate(False)

        self._hist_box = ctk.CTkScrollableFrame(
            self.hist_anim_content, height=160, fg_color=("gray97", "#0D1117"), corner_radius=8)
        self._hist_box.pack(fill="x", padx=14, pady=(0, 14))

        self._hist_empty_lbl = ctk.CTkLabel(
            self._hist_box, text="Henüz çeviri yok — altyazı taramasını başlatın",
            font=ctk.CTkFont(size=10), text_color="gray50"
        )
        self._hist_empty_lbl.pack(pady=12)

        # 3. ── Animasyon Mantığı (144 FPS Smooth Slide) ──
        self._hist_open = False
        self._hist_animating = False

        def _toggle_hist(_e=None):
            if self._hist_animating:
                return
            self._hist_animating = True

            target_h = 174  # Kutu yüksekliği (160) + Y-Boşluk (14)
            current_h = self.hist_anim_content.winfo_height()
            self.hist_anim_content.pack_propagate(False)

            if self._hist_open:
                # Kapanma Modu
                self.hist_arrow.configure(text="▸")
                hist_title.configure(text_color=("gray50", "#8B949E"))
                step = -15  # Yumuşak adım
            else:
                # Açılma Modu
                self.hist_arrow.configure(text="▾")
                hist_title.configure(text_color=("gray40", "#58A6FF"))
                self.hist_anim_content.pack(fill="x", padx=0, pady=0)
                step = 15

            def animate_hist():
                nonlocal current_h
                current_h += step
                
                if (step < 0 and current_h <= 1) or (step > 0 and current_h >= target_h):
                    if step < 0:
                        self.hist_anim_content.configure(height=1)
                        self.hist_anim_content.pack_forget()
                        self._hist_open = False
                    else:
                        self.hist_anim_content.configure(height=target_h)
                        self.hist_anim_content.pack_propagate(True)
                        self._hist_open = True
                    self._hist_animating = False
                else:
                    self.hist_anim_content.configure(height=current_h)
                    self.root.after(7, animate_hist)  # 1000ms / 144fps ≈ 7ms hızında kare atlat

            animate_hist()

        # Fare tıklamasını bileşenlere bağla (Temizle butonuna bağlamadık ki karışmasın)
        hist_hdr.bind("<Button-1>", _toggle_hist)
        self.hist_arrow.bind("<Button-1>", _toggle_hist)
        hist_title.bind("<Button-1>", _toggle_hist)

        # ── Kısayollar Kartı (Row 4, Cols 0-2) ────────────────────────────
        key_card = ctk.CTkFrame(scroll, fg_color=("white", "#13161F"),
                                corner_radius=14, border_width=1,
                                border_color=("gray80", "#30363D"))
        key_card.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12))

        # Header
        hdr_key = ctk.CTkFrame(key_card, fg_color="transparent")
        hdr_key.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(hdr_key, text="⌨  KISAYOLLAR",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

        # Content
        key_content = ctk.CTkFrame(key_card, fg_color="transparent")
        key_content.pack(fill="x", padx=14, pady=(0, 14))

        # Toggle button
        self._hotkey_toggle_btn = ctk.CTkButton(
            key_content, text="⌨ Hotkeys: Enabled", fg_color="#238636",
            hover_color="#1E7A30", height=28, command=self.toggle_hotkeys
        )
        self._hotkey_toggle_btn.pack(pady=(4, 6), fill="x")

        # Shortcuts box
        hot_box = ctk.CTkFrame(key_content, fg_color=("gray88", "#161924"), corner_radius=8)
        hot_box.pack(fill="x", pady=(4, 0))
        for act, key in [
            ("Select Region",     "Ctrl+1"),
            ("Start/Stop",        "Ctrl+2"),
            ("Center Overlay",    "Ctrl+3"),
            ("Exit",              "Ctrl+Q"),
        ]:
            row = ctk.CTkFrame(hot_box, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=act, font=ctk.CTkFont(size=10),
                         text_color="gray50").pack(side="left")
            ctk.CTkLabel(row, text=key, font=ctk.CTkFont(size=10, weight="bold"),
                         fg_color=("gray80", "#21262D"), corner_radius=4,
                         padx=6).pack(side="right")

    def _make_engine_card(self, parent: Any, key: str, meta: Dict) -> ctk.CTkFrame:
        is_installed = self._check_installed(key)
        is_selected  = (self.engine_var.get() == key)

        # ─ Renk palet: kurulmamışsa gri ──────────────────────────────
        if is_installed:
            card_bg  = ("white", "#13161F")
            bdr_clr  = "#238636" if is_selected else ("gray78", "#30363D")
            txt_clr  = ("gray20", "#E6EDF3")
            sub_clr  = ("gray40", "#8B949E")
            req_clr  = ("gray60", "#6E7681")
            cursor   = "hand2"
        else:
            card_bg  = (("gray88", "#0A0D13"))
            bdr_clr  = ("gray75", "#1A1F2E")
            txt_clr  = ("gray60", "#484F58")
            sub_clr  = ("gray60", "#484F58")
            req_clr  = ("gray70", "#3A3F47")
            cursor   = "arrow"

        card = ctk.CTkFrame(
            parent,
            fg_color=card_bg,
            corner_radius=12,
            border_width=2,
            border_color=bdr_clr,
            cursor=cursor,
        )

        def _select(_e: Any = None, k: str = key) -> None:
            if not is_installed:
                return   # kurulmamış — tıklamaya tepki vermez
            # --- MOTOR ÇALIŞIRKEN DEĞİŞTİRMEYİ ENGELLE ---
            if hasattr(self, "panel_sub") and getattr(self.panel_sub.engine, "running", False):
                return
            # ---------------------------------------------
            self.engine_var.set(k)

        card.bind("<Button-1>", _select)

        # İkon + başlık
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 4))
        top.bind("<Button-1>", _select)

        icon_lbl = ctk.CTkLabel(top, text=meta["icon"], font=ctk.CTkFont(size=22),
                                text_color=txt_clr)
        icon_lbl.pack(side="left")
        icon_lbl.bind("<Button-1>", _select)

        name_lbl = ctk.CTkLabel(
            top, text=meta["label"],
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#7EE787" if is_installed else txt_clr,
        )
        name_lbl.pack(side="left", padx=8)
        name_lbl.bind("<Button-1>", _select)

        # Kurulum rozeti
        if is_installed:
            badge_txt = "✓ Hazır"
            badge_clr = ("#1E7A30", "#238636")
        else:
            badge_txt = "✗ Kurulmadı"
            badge_clr = ("gray65", "#3A3F47")
        badge = ctk.CTkLabel(top, text=badge_txt, font=ctk.CTkFont(size=13),
                             fg_color=badge_clr, corner_radius=6, padx=6, pady=2,
                             text_color="white" if is_installed else txt_clr)
        badge.pack(side="right")
        badge.bind("<Button-1>", _select)

        # Sistem bilgi satırları (yeni)
        for ico, field in [
            ("⚽", "load"), ("🌐", "net"), ("💾", "needs")
        ]:
            if field in meta:
                row = ctk.CTkFrame(card, fg_color="transparent")
                row.pack(anchor="w", padx=12, pady=(1, 0))
                ctk.CTkLabel(row, text=ico, font=ctk.CTkFont(size=10),
                             text_color=req_clr, width=16).pack(side="left")
                ctk.CTkLabel(row, text=meta[field], font=ctk.CTkFont(size=9),
                             text_color=req_clr, justify="left").pack(side="left", padx=2)
                row.bind("<Button-1>", _select)

        # Avantaj / dezavantaj
        for field in ("pros", "cons"):
            if field in meta:
                lbl = ctk.CTkLabel(card, text=meta[field],
                                   font=ctk.CTkFont(size=9),
                                   text_color="#3FB950" if field == "pros" else "#D29922",
                                   justify="left", anchor="w", wraplength=210)
                lbl.pack(anchor="w", padx=12, pady=(2, 0))
                lbl.bind("<Button-1>", _select)

        # Eski özet satırı
        desc_lbl = ctk.CTkLabel(
            card, text=meta["req"],
            font=ctk.CTkFont(size=9),
            text_color=req_clr, justify="left",
        )
        desc_lbl.pack(anchor="w", padx=12, pady=(4, 6))
        desc_lbl.bind("<Button-1>", _select)

        # Hibrit için Radiobutton paneli (standart moda göre tasarım)
        if key == "hybrid":
            sep_rb = ctk.CTkFrame(card, fg_color=("gray82", "#21262D"), height=1)
            sep_rb.pack(fill="x", padx=12, pady=(6, 2))

            rb_hdr = ctk.CTkLabel(
                card, text="⚙  Hibrit Çalışma Prensibi",
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=sub_clr, anchor="w",
            )
            rb_hdr.pack(anchor="w", padx=12, pady=(2, 0))
            rb_hdr.bind("<Button-1>", _select)

            rb_std = ctk.CTkRadioButton(
                card,
                text="Standart Mod (Tasarruf)  —  yalnızca gerektiğinde EasyOCR",
                variable=self.hybrid_mode_var, value="standard",
                font=ctk.CTkFont(size=9), text_color=sub_clr,
            )
            rb_std.pack(anchor="w", padx=20, pady=(2, 0))

            rb_agg = ctk.CTkRadioButton(
                card,
                text="Agresif Mod (Performans)  —  iki motoru aynı anda çalıştır",
                variable=self.hybrid_mode_var, value="aggressive",
                font=ctk.CTkFont(size=9), text_color=sub_clr,
            )
            rb_agg.pack(anchor="w", padx=20, pady=(2, 6))

        # Kur / Kaldır butonu (standart ve hybrid için yok)
        if key not in ("standard", "hybrid"):
            action = "uninstall" if is_installed else "install"
            btn_txt = "🗑  Kaldır" if is_installed else "⬇  Kur"
            btn_clr = "#DA3633" if is_installed else "#1F6FEB"
            task_key = f"{key}_{action}"
            ctk.CTkButton(
                card, text=btn_txt, height=28, width=100,
                fg_color=btn_clr, hover_color="#B62D2A" if is_installed else "#1A5FCC",
                font=ctk.CTkFont(size=11),
                command=lambda tk=task_key: self._run_install_task(tk),
            ).pack(pady=(0, 12))
        elif key != "hybrid":   # hybrid zaten radiobutton alanıyla biter
            ctk.CTkLabel(card, text="").pack(pady=6)

        return card

    def _check_installed(self, key: str) -> bool:
        if key in ("standard", "hybrid"):
            return True   # Her ikisi de ek kurulum gerektirmez
        if key == "advanced":
            return (importlib.util.find_spec("easyocr") is not None and
                    importlib.util.find_spec("torch") is not None)
        return False

    def _refresh_glow(self) -> None:
        """Aktif motoru yeşil, hazır olanları sarı glow ile vurgula. Motor çalışırken diğerlerini uyut."""
        act = self.engine_var.get()
        
        # Tarama motoru şu an çalışıyor mu kontrol et
        is_running = hasattr(self, "panel_sub") and getattr(self.panel_sub.engine, "running", False)
        
        for key, frame in self._eng_frames.items():
            is_selected = (key == act)
            is_installed = self._check_installed(key)
            
            if is_installed:
                if is_selected:
                    frame.configure(border_color="#238636") # Seçili olan hep yeşil kalır
                else:
                    # Seçili değilse: Motor çalışıyorsa sönük griye dön, çalışmıyorsa sarı (hazır) ol
                    frame.configure(border_color=("gray75", "#1A1F2E") if is_running else "#D29922")
            else:
                # Kurulmamış olanlar her halükarda sönük gridir
                frame.configure(border_color=("gray75", "#1A1F2E"))


    def _refresh_engine_cards(self) -> None:
        """Motor kartlarını tamamen yeniden çiz (kurulum sonrası)."""
        ec_row = getattr(self, "_ec_row", None)
        if not ec_row:
            _log("Hata: _ec_row bulunamadı — _refresh_engine_cards çalışamıyor.", "ERROR")
            return

        for frame in self._eng_frames.values():
            frame.destroy()
        self._eng_frames.clear()

        for col, (key, meta) in enumerate(self.ENGINE_META.items()):
            f = self._make_engine_card(ec_row, key, meta)
            f.grid(row=0, column=col, padx=5, sticky="nsew")
            self._eng_frames[key] = f
        self._refresh_glow()

    # ── Kurulum / Kaldırma ─────────────────────────────────────────────────────
    def _run_install_task(self, task_key: str) -> None:
        """Kurulum/kaldırma başlatır ve aktif butonu 'İptal' moduna geçirir."""
        self._install_stop.clear()
        self._installed_pkgs.clear()
        self._prog_bar.set(0)
        self._prog_bar.pack(fill="x", padx=18, pady=(6, 0))
        self._prog_lbl.pack(pady=(2, 8))
        # İlgili motor kartındaki aksiyon butonunu bul ve değiştir
        engine_key = task_key.split("_")[0]
        self._set_engine_btn(engine_key, cancel_mode=True)
        threading.Thread(target=self._install_thread, args=(task_key,), daemon=True).start()

    def _set_engine_btn(self, engine_key: str, cancel_mode: bool) -> None:
        """Motor kartındaki Kur/Kaldır butonunu İptal/Orijinal moduna geçirir."""
        frame = self._eng_frames.get(engine_key)
        if not frame:
            return
        # Karttaki tek CTkButton'u bul
        for w in frame.winfo_children():
            if isinstance(w, ctk.CTkButton) and w.cget("text") not in ("⬛", "▶"):
                if cancel_mode:
                    w.configure(text="⛔  İptal", fg_color="#6E7681", hover_color="#555",
                                command=self._cancel_install)
                else:
                    is_installed = self._check_installed(engine_key)
                    txt = "🗑  Kaldır" if is_installed else "⬇  Kur"
                    clr = "#DA3633" if is_installed else "#1F6FEB"
                    task_key = f"{engine_key}_{'uninstall' if is_installed else 'install'}"
                    w.configure(text=txt, fg_color=clr,
                                hover_color="#B62D2A" if is_installed else "#1A5FCC",
                                command=lambda tk=task_key: self._run_install_task(tk))
                break

    def _cancel_install(self) -> None:
        """Devam eden kurulum/kaldırmayı durdurur ve geri alır."""
        self._install_stop.set()
        if self._install_proc and self._install_proc.poll() is None:
            self._install_proc.terminate()
        self.root.after(0, lambda: self._prog_lbl.configure(text="⏹ İptal ediliyor…"))

    def _pip_run(self, args: List[str]) -> bool:
        """pip komutunu çalıştırır; iptal sinyali gelirse False döndürür."""
        if self._install_stop.is_set():
            return False
        cmd = [sys.executable, "-m", "pip"] + args
        _log(f"[pip] Komutu: {' '.join(args)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._install_proc = proc
        out_lines: List[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                out_lines.append(line)
                # Son satırı UI'ya yansıt
                self.root.after(0, lambda l=line: self._prog_lbl.configure(
                    text=l[:80]
                ))
            if self._install_stop.is_set():
                proc.terminate()
                _log("[pip] İptal edildi.", "WARN")
                return False
        proc.wait()
        self._install_proc = None
        success = proc.returncode == 0
        _log(f"[pip] Çıkış kodu: {proc.returncode} {'✓' if success else '✗'}")
        if not success and out_lines:
            _log(f"[pip] Hata çıktısı (son 5 satır):\n" + "\n".join(out_lines[-5:]), "ERROR")
        return success

    def _install_thread(self, task_key: str) -> None:
        engine_key = task_key.split("_")[0]
        cancelled = False

        def prog(v: float, msg: str) -> None:
            self.root.after(0, lambda: self._prog_bar.set(v))
            self.root.after(0, lambda: self._prog_lbl.configure(text=msg))

        try:
            if task_key == "advanced_install":
                _log(f"[Kurulum] EasyOCR GPU kurulumu başladı.")
                # 1. Önce opencv-python kaldır (cv2.pyd kilitli olabilir, headless ile çakışır)
                prog(0.05, "Mevcut OpenCV kaldırılıyor…")
                _log("[Kurulum] opencv-python kaldırılıyor (headless ile çakışma önlemi)…")
                self._pip_run(["uninstall", "opencv-python", "-y"])
                self._installed_pkgs.append("__opencv_removed__")  # geri alma işareti

                # 2. PyTorch
                prog(0.15, "PyTorch indiriliyor… (2-3 dk)")
                if not self._pip_run(["install", "torch", "torchvision",
                                      "--extra-index-url", "https://download.pytorch.org/whl/cu118"]):
                    cancelled = True
                    _log("[Kurulum] PyTorch kurulumu başarısız veya iptal edildi.", "ERROR")
                else:
                    self._installed_pkgs += ["torch", "torchvision"]
                    prog(0.65, "EasyOCR indiriliyor…")
                    if not self._pip_run(["install", "easyocr"]):
                        cancelled = True
                        _log("[Kurulum] EasyOCR kurulumu başarısız.", "ERROR")
                    else:
                        self._installed_pkgs.append("easyocr")
                        _log("[Kurulum] EasyOCR GPU kurulumu tamamlandı.")


            elif task_key == "advanced_uninstall":
                _log("[Kaldırma] EasyOCR kaldırılıyor…")
                prog(0.3, "EasyOCR kaldırılıyor…")
                if not self._pip_run(["uninstall", "easyocr", "-y"]):
                    cancelled = True
                else:
                    prog(0.7, "PyTorch kaldırılıyor…")
                    self._pip_run(["uninstall", "torch", "torchvision", "-y"])
                    _log("[Kaldırma] EasyOCR + PyTorch kaldırıldı.")

            # hybrid motoru için kurulum/kaldırma gerekmez — bu nokta hiç çalışmaz
            # (güvenlik için boş bırakıldı)

            if cancelled or self._install_stop.is_set():
                _log(f"[Kurulum] İptal/geri alma: {self._installed_pkgs}", "WARN")
                # opencv özel işaretini ayır
                need_opencv = "__opencv_removed__" in self._installed_pkgs
                real_pkgs = [p for p in self._installed_pkgs if not p.startswith("__")]
                if real_pkgs:
                    prog(0.0, "🔄 Geri alınıyor…")
                    self._pip_run(["uninstall", "-y"] + real_pkgs)
                if need_opencv:
                    prog(0.0, "🔄 OpenCV geri yükleniyor…")
                    _log("[Geri alma] opencv-python yeniden kuruluyor…", "WARN")
                    self._pip_run(["install", "opencv-python"])
                self.root.after(0, lambda: self._finish_install(cancelled=True,
                                                                engine_key=engine_key))
            else:
                _log(f"[Kurulum] Başarıyla tamamlandı: {task_key}")
                prog(1.0, "✓ Tamamlandı!")
                time.sleep(1.5)
                self.root.after(0, lambda: self._finish_install(cancelled=False,
                                                                engine_key=engine_key))

        except Exception as exc:
            import traceback
            _log(f"[Kurulum KRITIK Hata] {task_key}: {exc}\n{traceback.format_exc()}", "CRITICAL")
            self.root.after(0, lambda: self._prog_lbl.configure(
                text=f"⚠ Hata: {str(exc)[:55]}"))
            self.root.after(0, lambda: self._finish_install(cancelled=True,
                                                            engine_key=engine_key))

    def _finish_install(self, cancelled: bool = False, engine_key: str = "") -> None:
        self._prog_bar.pack_forget()
        self._prog_lbl.pack_forget()
        self._install_stop.clear()
        self._installed_pkgs.clear()
        self._refresh_engine_cards()

    # ── Görünüm Kontrolleri ───────────────────────────────────────────────────
    def _pick_color(self, name: str) -> None:
        self.font_color_var.set(name)
        for n, b in self._color_btns.items():
            is_sel = (n == name)
            # CustomTkinter bug'ını aşmak için:
            # Kenarlık hep 2 piksel kalır, seçili değilse butonun kendi rengine bürünerek gizlenir.
            hex_c = FONT_COLORS.get(n, "#FFFFFF")
            b.configure(
                border_width=2,
                border_color="#58A6FF" if is_sel else hex_c,
            )
        self._apply_style()

    def _pick_speed(self, val: str) -> None:
        self.interval_var.set(val)
        for v, b in self._spd_btns.items():
            b.configure(fg_color="#1F6FEB" if v == val else "gray30")

    def _pick_ui_scale(self, val: str) -> None:
        """Arayüz ölçeğini değiştir (tüm widget'lar otomatik güncellenir)."""
        self._ui_scale_var.set(val)
        scale = float(val)
        ctk.set_widget_scaling(scale)
        ctk.set_window_scaling(scale)
        for v, b in self._scale_btns.items():
            b.configure(fg_color="#1F6FEB" if v == val else "gray30")

    def _toggle_theme(self) -> None:
        """Koyu / Açık tema arasında geçiş."""
        self._dark_mode = not self._dark_mode
        mode = "dark" if self._dark_mode else "light"
        ctk.set_appearance_mode(mode)
        self._theme_btn.configure(
            text="🌙 Koyu" if self._dark_mode else "☀️ Açık"
        )

    def _add_to_history(self, text: str) -> None:
        """Tekilleştirilmiş çeviri geçmişine yeni giriş ekle (non-blocking)."""
        key = text.strip()[:120]
        if not key or key in self._tr_history_seen:
            return
        self._tr_history_seen.add(key)
        self._tr_history.appendleft(key)
        if len(self._tr_history_seen) > 60:
            self._tr_history_seen = set(list(self._tr_history))
        # Geçmiş render'ını ana döngüye ertele — çeviri akışını bloklamaz
        self.root.after(50, self._render_history)

    def _render_history(self) -> None:
        """Geçmiş kutusu etiketlerini yeniden çiz."""
        # Mevcut etiketleri sil
        for lbl in self._hist_labels:
            lbl.destroy()
        self._hist_labels.clear()

        if not self._tr_history:
            self._hist_empty_lbl.pack(pady=12)
            return
        self._hist_empty_lbl.pack_forget()

        for i, txt in enumerate(self._tr_history):
            row = ctk.CTkFrame(self._hist_box, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=1)
            idx_lbl = ctk.CTkLabel(
                row, text=f"{i+1:02d}",
                width=22, font=ctk.CTkFont(size=9),
                text_color=("gray60", "#484F58"),
            )
            idx_lbl.pack(side="left")
            txt_lbl = ctk.CTkLabel(
                row, text=txt,
                font=ctk.CTkFont(size=10),
                text_color=("gray20", "#C9D1D9"),
                justify="left", anchor="w",
                wraplength=520,
            )
            txt_lbl.pack(side="left", padx=4, fill="x", expand=True)
            self._hist_labels.append(row)

    def _clear_history(self) -> None:
        self._tr_history.clear()
        self._tr_history_seen.clear()
        self._render_history()

    def _pick_size_preset(self, size: int) -> None:
        self.font_size_var.set(size)
        for sz, b in self._size_btns.items():
            b.configure(fg_color="#1F6FEB" if sz == size else "gray30")
        self._apply_style()

    def _adj_size(self, delta: int) -> None:
        new = max(10, min(48, self.font_size_var.get() + delta))
        self.font_size_var.set(new)
        # Önayar butonlardan hiçbirini seçili yapmaz (özel değer)
        for b in self._size_btns.values():
            b.configure(fg_color="gray30")
        self._apply_style()

    def _toggle_bold(self) -> None:
        self.font_bold_var.set(not self.font_bold_var.get())
        self._bold_btn.configure(
            fg_color="#1F6FEB" if self.font_bold_var.get() else "gray30"
        )
        self._apply_style()

    def _apply_style(self, *_: Any) -> None:
        cfg = self.get_overlay_config()
        ov = self.panel_sub.engine.overlay
        if ov:
            if not any(ov._lines):
                ov.push_line("Ayar Önizlemesi...")
            ov.set_style(
                cfg["font_size"], cfg["font_family"],
                cfg["font_color"], cfg["font_bold"],
            )

    # ── Kısayollar ────────────────────────────────────────────────────────────
    def _setup_hotkeys(self) -> None:
        if keyboard is None:
            return
        self._hotkeys_enabled = getattr(self, "_hotkeys_enabled", True)
        if not self._hotkeys_enabled:
            return
        self._register_hotkeys()

    def _register_hotkeys(self) -> None:
        """Mevcut hook'ları temizleyip yeniden kaydet — taşmayı önler."""
        if keyboard is None:
            return
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        if not getattr(self, "_hotkeys_enabled", True):
            return
        try:
            keyboard.add_hotkey("ctrl+1", lambda: self.root.after(0, self.panel_sub.select_region))
            keyboard.add_hotkey("ctrl+2", lambda: self.root.after(0, self.panel_sub.toggle))
            keyboard.add_hotkey("ctrl+3", lambda: self.root.after(0, self._reset_overlays))
            keyboard.add_hotkey("ctrl+q", lambda: self.root.after(0, self.quit))
        except Exception:
            pass

    def toggle_hotkeys(self) -> None:
        """Kısayol tuşlarını etkinleştir / devre dışı bırak."""
        self._hotkeys_enabled = not getattr(self, "_hotkeys_enabled", True)
        if keyboard is None:
            return
        if self._hotkeys_enabled:
            self._register_hotkeys()
        else:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        # Toggle butonunu güncelle
        if hasattr(self, "_hotkey_toggle_btn"):
            if self._hotkeys_enabled:
                self._hotkey_toggle_btn.configure(
                    text="⌨ Kısayollar: Açık", fg_color="#238636"
                )
            else:
                self._hotkey_toggle_btn.configure(
                    text="⌨ Kısayollar: Kapalı", fg_color="gray30"
                )

    def _reset_overlays(self) -> None:
        if self.panel_sub.engine.overlay:
            self.panel_sub.engine.overlay.reset_position()

    # ── Ayarlar ───────────────────────────────────────────────────────────────
    def _load_settings(self) -> None:
        if not os.path.exists(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.src_lang_var.set(d.get("src_lang", "İngilizce (EN)"))
            self.tgt_lang_var.set(d.get("tgt_lang", "Türkçe (TR)"))
            self.interval_var.set(d.get("interval", "0.5"))
            self.font_size_var.set(int(d.get("font_size", 18)))
            self.font_color_var.set(d.get("font_color", "Beyaz"))
            self.font_family_var.set(d.get("font_family", "Segoe UI"))
            self.font_bold_var.set(bool(d.get("font_bold", True)))
            self.engine_var.set(d.get("engine", "standard"))
            self.hybrid_mode_var.set(d.get("hybrid_mode", "standard"))
            # Arayüz ölçeği
            self._ui_scale_var.set(d.get("ui_scale", "1.0"))
            scale = float(self._ui_scale_var.get())
            if scale != 1.0:
                ctk.set_widget_scaling(scale)
                ctk.set_window_scaling(scale)
            # Çeviri motoru
            self.translation_engine_var.set(d.get("translation_engine", "google"))
            self.gemini_key_var.set(d.get("gemini_key", ""))
            # OCR hassasiyet
            self.ocr_quality_thresh_var.set(d.get("ocr_quality_thresh", "40"))
            self.ocr_stab_window_var.set(d.get("ocr_stab_window", "6"))
            self.ocr_stab_thresh_var.set(d.get("ocr_stab_thresh", "0.50"))
        except Exception:
            pass

    def _save_settings(self) -> None:
        d = {
            "src_lang":    self.src_lang_var.get(),
            "tgt_lang":    self.tgt_lang_var.get(),
            "interval":    self.interval_var.get(),
            "font_size":   self.font_size_var.get(),
            "font_color":  self.font_color_var.get(),
            "font_family": self.font_family_var.get(),
            "font_bold":   self.font_bold_var.get(),
            "engine":      self.engine_var.get(),
            "ui_scale":    self._ui_scale_var.get(),
            "hybrid_mode": self.hybrid_mode_var.get(),
            # Çeviri motoru
            "translation_engine": self.translation_engine_var.get(),
            "gemini_key":         self.gemini_key_var.get(),
            # OCR hassasiyet
            "ocr_quality_thresh": self.ocr_quality_thresh_var.get(),
            "ocr_stab_window":    self.ocr_stab_window_var.get(),
            "ocr_stab_thresh":    self.ocr_stab_thresh_var.get(),
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ── OCR Motoru Başlatma ────────────────────────────────────────────────────
    def _init_ocr(self) -> None:
        self._hw_suffix = ""  # HardwareDetector bitince doldurulur

        def _load() -> None:
            import traceback
            global _active_ocr_engine
            _log(f"--- Uygulama Başlatıldı: Python {sys.version} ---", "INFO")
            try:
                sel_engine = self.engine_var.get()
                if sel_engine == "hybrid":
                    # HybridOCREngine doğrudan başlatılır (HardwareDetector bypass)
                    _active_ocr_engine = HybridOCREngine(self.hybrid_mode_var)
                    self._hw_suffix    = "🔀 Hibrit OCR (WinOCR + EasyOCR)"
                    _log(f"Aktif OCR motoru: {self._hw_suffix}")
                else:
                    hw = HardwareDetector.detect()
                    _active_ocr_engine = hw["engine"]
                    if _active_ocr_engine is None:
                        _log("KRITIK: OCR motoru None döndü — hiçbir motor yüklenemedi!", "CRITICAL")
                    self._hw_suffix = hw.get("engine_name", "")
                    _log(f"Aktif OCR motoru: {self._hw_suffix}")
            except Exception as exc:
                _log(f"KRITIK _init_ocr hatası: {exc}\n{traceback.format_exc()}", "CRITICAL")
                self._hw_suffix = "⚠ Motor Yüklenemedi"
            # Motor etiketi UI güncelle
            labels = {
                "standard": "💨 Windows OCR",
                "advanced": "⚡ EasyOCR GPU",
                "hybrid":   "🔀 Hibrit OCR",
            }
            sel = labels.get(self.engine_var.get(), "💨 Windows OCR")
            hw_txt = self._hw_suffix
            engine_ok = _active_ocr_engine is not None
            self.root.after(
                0,
                lambda s=sel, h=hw_txt, ok=engine_ok: self._ocr_status.configure(
                    text=f"{s}{(' — ' + h) if h else ''}" if ok else f"⚠ Motor Yüklenemedi — app_log.txt inceleyin",
                    text_color="#7EE787" if ok else "#DA3633",
                ),
            )
        threading.Thread(target=_load, daemon=True).start()

    # ── Çıkış ─────────────────────────────────────────────────────────────────
   # ── Rastgele ve Dinamik Açılış Ekranı (Splash Screen) ─────────────────────
    def _show_splash(self) -> None:
        self.root.withdraw()  # Ana programı gizle
        
        import random
        import wave
        import winsound
        from PIL import Image
        
        # 1, 2 veya 3 sayılarından birini rastgele seç
        secim = random.randint(1, 3)
        
        # Dosya yollarını seçilen sayıya göre belirle
        img_path = os.path.join(BASE_DIR, f"logo{secim}.png")
        ses_path = os.path.join(BASE_DIR, f"log{secim}.wav")
        
        # SESİN UZUNLUĞUNU OTOMATİK HESAPLA (Milisaniye cinsinden)
        duration_ms = 3000  # Eğer ses bulunamazsa varsayılan 3 saniye
        if os.path.exists(ses_path):
            try:
                with wave.open(ses_path, 'r') as w:
                    frames = w.getnframes()
                    rate = w.getframerate()
                    duration_ms = int((frames / float(rate)) * 1000)
            except Exception:
                pass
                
        # Siyah, çerçevesiz ekranı oluştur
        self.splash = ctk.CTkToplevel(self.root)
        self.splash.overrideredirect(True)
        self.splash.attributes("-topmost", True)
        
        # Başlangıçta tamamen saydam (görünmez) yap
        self.splash.attributes("-alpha", 0.0) 
        self.splash.configure(fg_color="#010101")
        
        # Ekranı tam merkeze ortala (256x256 boyutunda)
        w, h = 256, 256
        self.splash.update_idletasks()
        x = (self.splash.winfo_screenwidth() // 2) - (w // 2)
        y = (self.splash.winfo_screenheight() // 2) - (h // 2)
        self.splash.geometry(f"{w}x{h}+{x}+{y}")
        
        # Seçilen Logoyu Ekrana Bas
        splash_label = ctk.CTkLabel(self.splash, text="")
        splash_label.pack(expand=True)
        try:
            logo_img = ctk.CTkImage(light_image=Image.open(img_path), size=(256, 256))
            splash_label.configure(image=logo_img, text="")
        except Exception:
            splash_label.configure(text=f"🚀 YÜKLENİYOR...", font=ctk.CTkFont(size=20, weight="bold"), text_color="#58A6FF")
            
        # Seçilen Sesi Çal (SND_MEMORY + Threading çözümü)
        if os.path.exists(ses_path):
            try:
                # Dosyayı byte olarak belleğe okuyoruz (Türkçe karakter sorununu aşmak için)
                with open(ses_path, "rb") as ses_dosyasi:
                    ses_verisi = ses_dosyasi.read()
                
                # SND_ASYNC kullanamadığımız için sesi ayrı bir iş parçacığında (Thread) çalıyoruz
                import threading
                def arka_planda_cal():
                    try:
                        import winsound
                        # Sadece SND_MEMORY kullanıyoruz, Thread içinde olduğu için programı dondurmaz
                        winsound.PlaySound(ses_verisi, winsound.SND_MEMORY)
                    except Exception as e:
                        print(f"Thread içi ses hatası: {e}")
                
                # Ses thread'ini başlat
                threading.Thread(target=arka_planda_cal, daemon=True).start()
                
            except Exception as e:
                print(f"Ses okunurken bir hata oluştu: {e}")
            
        # --- ANİMASYON (BELİRME VE KARARMA) MANTIĞI ---
        # Toplam sürenin %15'i belirme, %15'i kararma, kalanı ise tam görünür kalma süresi olsun
        fade_time = int(duration_ms * 0.15)
        stay_time = duration_ms - (fade_time * 2)
        steps = 20 # Animasyon akıcılığı için adım sayısı

        def fade_in(step=0):
            if not hasattr(self, 'splash') or not self.splash.winfo_exists():
                return
            if step <= steps:
                alpha = step / steps
                try:
                    self.splash.attributes("-alpha", alpha)
                except Exception:
                    return
                self.root.after(fade_time // steps, lambda: fade_in(step + 1))
            else:
                # Belirme bitti, ekranda sabit kalması için bekle, sonra kararmaya başla
                self.root.after(max(0, stay_time), lambda: fade_out(steps))

        def fade_out(step=steps):
            if not hasattr(self, 'splash') or not self.splash.winfo_exists():
                return
            if step >= 0:
                alpha = step / steps
                try:
                    self.splash.attributes("-alpha", alpha)
                except Exception:
                    return
                self.root.after(fade_time // steps, lambda: fade_out(step - 1))
            else:
                # Kararma bitti, ekranı kapat
                self._close_splash()

        # Animasyonu başlat
        fade_in()

    def _close_splash(self) -> None:
        if hasattr(self, "splash") and self.splash.winfo_exists():
            self.splash.destroy()
        self.root.deiconify()
        self.root.focus_force()
    def _test_gemini_key(self) -> None:
        """Kullanıcının girdiği Gemini API anahtarını arka planda test eder."""
        key = self.gemini_key_var.get().strip()
        
        if not key:
            self._api_status_lbl.configure(text="")
            self.gemini_entry.configure(border_color=("gray60", "#30363D"))
            return
            
        # UI'ı test moduna al
        self._api_status_lbl.configure(text="⏳ Test ediliyor...", text_color="#D29922")
        self.gemini_entry.configure(border_color="#D29922")
        
        def check_key():
            try:
                import google.generativeai as genai
                genai.configure(api_key=key)
                
                # Sadece modelleri listelemeyi denemek, anahtarın çalışıp çalışmadığını anlamak için yeterlidir
                list(genai.list_models()) 
                
                # Başarılı!
                self.root.after(0, lambda: self._api_status_lbl.configure(text="✓ Onaylandı", text_color="#7EE787"))
                self.root.after(0, lambda: self.gemini_entry.configure(border_color="#238636")) # Yeşil çerçeve
                self._save_settings()
                
            except Exception:
                # Başarısız!
                self.root.after(0, lambda: self._api_status_lbl.configure(text="✗ Geçersiz Anahtar", text_color="#DA3633"))
                self.root.after(0, lambda: self.gemini_entry.configure(border_color="#DA3633")) # Kırmızı çerçeve
                
        # Programı dondurmamak için ayrı bir iş parçacığında çalıştır
        import threading
        threading.Thread(target=check_key, daemon=True).start()
        
    def ping_translation_engine(self, engine_key: str) -> None:
        """Çeviri başarılı olduğunda ilgili motorun butonunu parlatır."""
        names = {"google": "🔵 Google", "gemini": "🌟 Gemini AI", "cache": "💾 Ön Bellek"}
        
        # Durum yazısını güncelle
        if hasattr(self, "_trans_desc_lbl") and self._trans_desc_lbl.winfo_exists():
            self._trans_desc_lbl.configure(
                text=f"Son Çeviri: {names.get(engine_key, engine_key)}", 
                text_color="#7EE787"
            )
            
        # İlgili butonu bul ve parlat
        btn = getattr(self, "_trans_btns", {}).get(engine_key)
        if btn and btn.winfo_exists():
            btn.configure(fg_color="#00FF88", text_color="black") # Neon Yeşil parlama
            
            # 400ms sonra orijinal rengine (Seçili veya Gri) geri dön
            def revert():
                if btn.winfo_exists():
                    is_sel = (self.translation_engine_var.get() == engine_key)
                    btn.configure(
                        fg_color="#238636" if is_sel else "gray40", 
                        text_color="white" if is_sel else ("gray20", "#C9D1D9")
                    )
            self.root.after(400, revert)

    def quit(self) -> None:
        self._save_settings()
        self.panel_sub.stop()
        if keyboard:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self.root.destroy()
        sys.exit(0)

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    App().run()
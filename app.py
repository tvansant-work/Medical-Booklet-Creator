import os
import sys

# ==========================================
# MAC OS "INVISIBLE LIBRARY" FIX
# ==========================================
if sys.platform == "darwin":
    try:
        # 1. Locate the 'lib' folder inside your Conda environment
        # (This finds where python is running from, then goes up and into 'lib')
        base_path = os.path.dirname(sys.executable)
        lib_path = os.path.abspath(os.path.join(base_path, "..", "lib"))
        
        # 2. Tell macOS strictly: "Look here for the missing engines"
        # We append to both library paths to cover all bases
        current_dyld = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{lib_path}:{current_dyld}"
        os.environ["DYLD_LIBRARY_PATH"] = f"{lib_path}:{os.environ.get('DYLD_LIBRARY_PATH', '')}"
        
        # 3. Optional: Print path to terminal so you can verify it worked
        print(f"✅ Mac Library Fix Applied: Pointing to {lib_path}")
        
    except Exception as e:
        print(f"⚠️ Library Fix Warning: {e}")
# ==========================================

import streamlit as st

# ── App-wide debug log capture ────────────────────────────────────
# Every print() in this file (photo matching, swimming/dietary/contact
# matching, error handlers, etc.) already writes helpful diagnostic
# detail — it just used to only go to whatever terminal happened to
# be running the server. This tees stdout so that output also
# accumulates in session_state, where it can be shown in-app and
# copied into an error report. Installed once per server process
# (Streamlit re-runs this script on every interaction, but the
# isinstance check below skips re-wrapping on subsequent runs).
class _DebugLogTee:
    def __init__(self, real_stream):
        self._real = real_stream
        self.is_debug_log_tee = True

    def write(self, data):
        self._real.write(data)
        try:
            chunks = st.session_state.setdefault("_debug_log_chunks", [])
            chunks.append(data)
            # Keep the buffer bounded so a very long session doesn't
            # grow without limit — trim oldest chunks once we're well
            # past what anyone would need for a bug report.
            # (Running total kept in session_state rather than recomputed
            # via sum(len(c) for c in chunks) on every write — with the
            # extraction code printing per-image debug lines, that sum()
            # was rescanning the whole buffer on every single write call,
            # i.e. O(n) work per write instead of O(1).)
            total_len = st.session_state.get("_debug_log_total_len", 0) + len(data)
            while total_len > 2_000_000 and len(chunks) > 1:
                total_len -= len(chunks.pop(0))
            st.session_state["_debug_log_total_len"] = total_len
        except Exception:
            pass
        return len(data)

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass

    def isatty(self):
        return getattr(self._real, "isatty", lambda: False)()


if not isinstance(sys.stdout, _DebugLogTee):
    sys.stdout = _DebugLogTee(sys.stdout)
if not isinstance(sys.stderr, _DebugLogTee):
    sys.stderr = _DebugLogTee(sys.stderr)


def _gather_environment_info():
    """A short, copy-pasteable snapshot of the environment, for bug reports."""
    import platform
    lines = []
    lines.append(f"Report generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"OS: {platform.platform()}")
    lines.append(f"Python: {sys.version.split()[0]} ({sys.executable})")
    try:
        lines.append(f"Streamlit: {st.__version__}")
    except Exception:
        pass
    try:
        import pandas as _pd_ver
        lines.append(f"Pandas: {_pd_ver.__version__}")
    except Exception:
        pass
    for fname, label in [(".install-method", "Install method"), (".conda-env-name", "Conda env")]:
        try:
            if os.path.exists(fname):
                with open(fname) as f:
                    lines.append(f"{label}: {f.read().strip()}")
        except Exception:
            pass
    return "\n".join(lines)


def _build_anonymization_map(df):
    """
    Map every real name/preferred-name/surname/student-ID value that
    appears in the roster to a stable, non-identifying code, e.g.
    "Cooper" -> "Surname014". The SAME real value always maps to the
    SAME code within a session, so duplicate-surname or repeated-name
    patterns (the exact kind of thing needed to diagnose a matching
    bug) are still visible in the anonymised log — you just can't
    tell which student it actually is from the text alone.
    """
    mapping = {}
    if df is None or getattr(df, "empty", True):
        return mapping
    try:
        def _values(col_key):
            col = COLS.get(col_key)
            if not col or col not in df.columns:
                return []
            return sorted(
                {str(v).strip() for v in df[col].dropna().astype(str) if str(v).strip()},
                key=str.lower,
            )

        for col_key, label in [
            ("surname", "Surname"),
            ("first_name", "First"),
            ("preferred_name", "Pref"),
            ("student_id", "ID"),
        ]:
            for i, val in enumerate(_values(col_key), 1):
                key = val.lower()
                if key not in mapping:
                    mapping[key] = f"{label}{i:03d}"
    except Exception:
        pass
    return mapping


def _anonymize_text(text, mapping):
    if not text or not mapping:
        return text
    # Longest values first so e.g. a surname that's a prefix of another
    # value doesn't get partially replaced before the fuller match runs.
    for real_val in sorted(mapping.keys(), key=len, reverse=True):
        if not real_val:
            continue
        pattern = r"(?<![A-Za-z0-9])" + re.escape(real_val) + r"(?![A-Za-z0-9])"
        text = re.sub(pattern, mapping[real_val], text, flags=re.IGNORECASE)
    return text



# Initialize Session State variables if they don't exist
if 'extraction_done' not in st.session_state:
    st.session_state.extraction_done = False
if 'auto_matches' not in st.session_state:
    st.session_state.auto_matches = {}
if 'unmatched_data' not in st.session_state:
    st.session_state.unmatched_data = []
if 'manual_selections' not in st.session_state:
    st.session_state.manual_selections = {} # Stores { 'path_to_image': 'student_id' }
if 'swimming_matched' not in st.session_state:
    st.session_state.swimming_matched = {}
if 'swimming_unmatched' not in st.session_state:
    st.session_state.swimming_unmatched = []
if 'swimming_manual_selections' not in st.session_state:
    st.session_state.swimming_manual_selections = {} # Stores { 'swim_idx': 'student_id' }
if 'dietary_matched' not in st.session_state:
    st.session_state.dietary_matched = {}
if 'dietary_unmatched' not in st.session_state:
    st.session_state.dietary_unmatched = []
if 'dietary_manual_selections' not in st.session_state:
    st.session_state.dietary_manual_selections = {} # Stores { 'dietary_idx': 'student_id' }
if 'photo_permissions_map' not in st.session_state:
    st.session_state.photo_permissions_map = {} # Stores { 'student_id': 'Yes'|'No'|'No Response' }
if 'active_feature' not in st.session_state:
    st.session_state.active_feature = None  # None | 'booklet' | 'group' | 'attachments'
if 'group_results' not in st.session_state:
    st.session_state.group_results = None  # Stores last ID Matcher results
if 'group_email_input' not in st.session_state:
    st.session_state.group_email_input = ""
if 'idm_input_type' not in st.session_state:
    st.session_state.idm_input_type = "Email"  # What the user is pasting in: Name | Student ID | Email
if 'idm_output_type' not in st.session_state:
    st.session_state.idm_output_type = "Student ID"  # What the user wants back: Name | Student ID | Email
if 'idm_name_manual_selections' not in st.session_state:
    st.session_state.idm_name_manual_selections = {}  # { review_item_key: row_dict } — Name-matching manual picks
if 'seqta_contact_matched' not in st.session_state:
    st.session_state.seqta_contact_matched = {}
if 'seqta_contact_unmatched' not in st.session_state:
    st.session_state.seqta_contact_unmatched = []
if 'seqta_contact_manual' not in st.session_state:
    st.session_state.seqta_contact_manual = {}
if 'custom_groups' not in st.session_state:
    st.session_state.custom_groups = []  # list of {'label': str, 'identifiers': [str]}
if 'custom_groups_ungrouped_checked' not in st.session_state:
    st.session_state.custom_groups_ungrouped_checked = False
if 'y8_camp_data' not in st.session_state:
    st.session_state.y8_camp_data = {}  # { student_id: { 'class': '8A', 'camp': 'Freycinet', ...survey cols... } }
if 'y9_groups_data' not in st.session_state:
    st.session_state.y9_groups_data = None  # { 'groups': [...], 'id_to_group': {norm_id: group_key}, 'warnings': [...] }
if 'y9_survey_matched' not in st.session_state:
    st.session_state.y9_survey_matched = {}  # { student_id: {'name','email','house','timestamp','scores':{label: '1'-'10'/'N/A'}} }
if 'y9_survey_unmatched' not in st.session_state:
    st.session_state.y9_survey_unmatched = []  # [ {..survey record.., '_index': int, '_suggest': {...} or None} ]
if 'y9_survey_manual' not in st.session_state:
    st.session_state.y9_survey_manual = {}  # { _index: student_id }
if 'camp_medication_matched' not in st.session_state:
    st.session_state.camp_medication_matched = {}  # { student_id: { 'name': str, 'medications': [str] } }
if 'camp_medication_unmatched' not in st.session_state:
    st.session_state.camp_medication_unmatched = []  # [ { 'student_name': str, 'medications': [str], 'index': key } ]
if 'camp_medication_manual' not in st.session_state:
    st.session_state.camp_medication_manual = {}  # { index_key: student_id }
if 'camp_permissions_matched' not in st.session_state:
    st.session_state.camp_permissions_matched = {}  # { student_id: {'antihistamine':T/F/None, 'ibuprofen':..., 'paracetamol':...} }
if 'camp_days' not in st.session_state:
    st.session_state.camp_days = 3
import pandas as pd
import zipfile
import yaml
import urllib.parse
import re
import difflib
import base64
import pdfplumber
import unicodedata
import requests
from io import BytesIO
from PIL import Image
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from pypdf import PdfWriter, PdfReader

# ---------------- CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
TEMP_DIR = os.path.join(BASE_DIR, "_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

st.set_page_config(
    page_title="Medical Booklet Tools",
    layout="wide",
    page_icon=Image.open(os.path.join(BASE_DIR, "app_icon.png")) if os.path.exists(os.path.join(BASE_DIR, "app_icon.png")) else "📋",
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": None
    }
)

try:
    with open("config.yaml", "r") as f:
        CONFIG = yaml.safe_load(f)
except FileNotFoundError:
    st.error("config.yaml not found.")
    st.stop()

COLS = CONFIG["column_mappings"]
SEVERITY_KEYWORDS = CONFIG["severity_keywords"]

# Roll group code → full display name. Unknown codes fall back to the raw value.
ROLLGROUP_NAMES = {
    "7M": "7 Mott",    "7B": "7 Backhouse", "7F": "7 Fry",
    "7O": "7 Oats",    "7P": "7 Penn",       "7W": "7 Walker",
    "8B": "8 Bracey",  "8R": "8 Rustin",     "8S": "8 Stowe",
    "8P": "8 Preston", "8K": "8 Knight",     "8T": "8 Tuke",
}

def expand_rollgroup(code):
    """Return full roll group name, or the raw code if not in the lookup."""
    return ROLLGROUP_NAMES.get(str(code).strip(), str(code).strip())

# ---------------- DATA DICTIONARIES ----------------
LEARNING_CODES = {
    "!Time": "Extra Time",
    "!RstBrk": "Rest Breaks",
    "!RstBrks": "Rest Breaks",
    "!RestBreak": "Rest Breaks",
    "!IndvRm": "Separate Room",
    "!SmallRoom": "Small Room",
    "!Calculator": "Calculator",
    "!Scribe": "Scribe",
    "!Rdr": "Reader",
    "!Reader": "Reader",
    "!Laptop": "Laptop Allowed",
    "!Music": "Music Allowed",
    "!Prompt": "Prompter",
    "!Typing": "Typing Allowed",
    "!VocText": "Voice-to-Text",
    "!Grammar": "Grammar Support",
    "!Sensory": "Sensory Breaks",
    "!Extension": "Extension Tasks",
    "!AstTech": "Assistive Technology",
    "!Spelling": "Spelling Support"
}

GLOSSARY = {
    "SLD": "Specific Learning Disorder",
    "ASD": "Autism Spectrum Disorder",
    "DCD": "Developmental Coordination Disorder"
}

# ---------------- HELPERS ----------------
def img_to_base64(path):
    if not path or not os.path.exists(path): return None
    with open(path, "rb") as f: return base64.b64encode(f.read()).decode()

def parse_tutor(text):
    """Extracts Tutor name from General Notes."""
    if not isinstance(text, str): return ""
    # Looks for "Tutor:" followed by text
    match = re.search(r'Tutor:\s*(.*)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""

def parse_family_alert(text):
    """
    Extracts Family Alert details from General Notes.
    Family Alert is optional (most students won't have one) and its value can
    span multiple lines, e.g.:
        Family Alert: Living arrangements are : Friday to Friday, alternate weeks
    Captures everything after "Family Alert:" up to the next blank-line-separated
    block (matching how the other General Notes fields are laid out) or the end
    of the text — not just up to the next colon, since the alert text itself may
    contain colons.
    """
    if not isinstance(text, str): return ""
    match = re.search(r'Family Alert:\s*(.*?)(?:\n\s*\n|\Z)', text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

def convert_file_to_images(file_obj):
    """
    Converts a file (PDF or Image) into a list of Base64 strings (one per page).
    Uses magic byte sniffing to detect file type reliably — never relies solely
    on the .name extension, which may be absent or wrong for BytesIO/UploadedFile.
    """
    images_b64 = []
    try:
        file_obj.seek(0)
        file_bytes = file_obj.read()

        if not file_bytes:
            return []

        file_buffer = BytesIO(file_bytes)
        fname = getattr(file_obj, 'name', '') or ''

        # Detect type by magic bytes first, then fall back to extension
        is_pdf = file_bytes[:4] == b'%PDF'
        is_png = file_bytes[:4] == b'\x89PNG'
        is_jpg = file_bytes[:3] == b'\xff\xd8\xff'
        name_says_pdf = fname.lower().endswith('.pdf')

        # Attachment compression settings:
        # 150 DPI and JPEG quality 72 give a good size/quality balance for
        # action plan documents. Max dimension cap prevents oversized scans
        # from inflating the PDF further.
        ATTACH_DPI     = 150
        ATTACH_QUALITY = 72
        ATTACH_MAX_PX  = 2000  # longest edge cap in pixels

        def _compress_img(im):
            """Resize if oversized, then return compressed JPEG bytes."""
            im = im.convert("RGB")
            w, h = im.size
            if max(w, h) > ATTACH_MAX_PX:
                scale = ATTACH_MAX_PX / max(w, h)
                im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=ATTACH_QUALITY, optimize=True)
            return base64.b64encode(buf.getvalue()).decode()

        if is_pdf or (name_says_pdf and not is_png and not is_jpg):
            with pdfplumber.open(file_buffer) as pdf:
                for page in pdf.pages:
                    im = page.to_image(resolution=ATTACH_DPI).original
                    images_b64.append(_compress_img(im))
        else:
            img = Image.open(file_buffer)
            images_b64.append(_compress_img(img))


    except Exception as e:
        fname = getattr(file_obj, 'name', 'unknown')

    return images_b64

# ---------------------------------------------------------------------------
# Attachment review (final check before a booklet is generated)
#   - long attachments (more than N pages)
#   - duplicate uploads (same name AND same size, within one student)
#   - several plans for the same medical condition
# ---------------------------------------------------------------------------
def _plan_pdf_offset(raw):
    return raw[:1024].find(b"%PDF-")


def plan_page_count(raw):
    """Pages in a PDF (images count as 1; unreadable files return 0)."""
    if not raw:
        return 0
    off = _plan_pdf_offset(raw)
    if off == -1:
        return 1
    pdf = raw[off:]
    try:
        rd = PdfReader(BytesIO(pdf), strict=False)
        if rd.is_encrypted:
            try:
                rd.decrypt("")
            except Exception:
                pass
        n = len(rd.pages)
        if n:
            return n
    except Exception:
        pass
    try:
        with pdfplumber.open(BytesIO(pdf)) as p:
            return len(p.pages)
    except Exception:
        return 0


def plan_thumbnails(raw, max_pages=40, dpi=40):
    """Small PNG previews (one per page, up to max_pages) for the review screen."""
    out = []
    try:
        off = _plan_pdf_offset(raw)
        if off != -1:
            with pdfplumber.open(BytesIO(raw[off:])) as pdf:
                for pg in pdf.pages[:max_pages]:
                    im = pg.to_image(resolution=dpi).original.convert("RGB")
                    b = BytesIO()
                    im.save(b, format="PNG")
                    out.append(b.getvalue())
        else:
            im = Image.open(BytesIO(raw)).convert("RGB")
            im.thumbnail((420, 600))
            b = BytesIO()
            im.save(b, format="PNG")
            out.append(b.getvalue())
    except Exception:
        pass
    return out


def _plan_file_key(sid, i, name, size):
    return f"{sid}|{i}|{name}|{size}"


def _read_plan_buf(f):
    try:
        f.seek(0)
        raw = f.read()
        f.seek(0)
        return raw
    except Exception:
        return b""


def scan_plan_issues(plan_map, id_to_name, max_pages=5, do_long=True, do_dupes=True, do_multi=True):
    """
    Look through the attachments about to go into the booklet and return the ones worth a human look.
    Each item: {key, sid, student, name, size, pages, is_pdf, reasons[], default('keep'|'remove'), raw}
    """
    infos = []
    for sid, fl in plan_map.items():
        for i, f in enumerate(fl):
            raw = _read_plan_buf(f)
            if not raw:
                continue
            name = getattr(f, "name", "") or "attachment"
            infos.append({
                "key": _plan_file_key(sid, i, name, len(raw)), "sid": sid, "i": i,
                "student": id_to_name.get(sid, sid), "name": name, "size": len(raw),
                "pages": plan_page_count(raw), "is_pdf": _plan_pdf_offset(raw) != -1,
                "condition": getattr(f, "plan_condition", None),
                "reasons": [], "default": "keep", "raw": raw,
            })

    if do_long:
        for it in infos:
            if it["pages"] > max_pages:
                it["reasons"].append(f"📄 {it['pages']} pages (longer than {max_pages})")

    if do_dupes:
        groups = {}
        for it in infos:
            groups.setdefault((it["sid"], it["name"].strip().lower(), it["size"]), []).append(it)
        for grp in groups.values():
            if len(grp) > 1:
                for k, it in enumerate(grp):
                    it["reasons"].append(f"📑 Uploaded {len(grp)} times (same name and size)")
                    if k > 0:
                        it["default"] = "remove"

    if do_multi:
        groups = {}
        for it in infos:
            c = _plan_norm(it["condition"])
            if c:
                groups.setdefault((it["sid"], c), []).append(it)
        for grp in groups.values():
            if len(grp) > 1:
                for it in grp:
                    it["reasons"].append(f"🗂️ {len(grp)} plans attached for “{it['condition']}” — an older one may need removing")

    # Files that belong together (identical uploads, or plans for the same condition) are linked so the
    # review can show them side by side. Anything with 2+ linked files gets a group number.
    parent = list(range(len(infos)))

    def _find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[rb] = ra

    idx_of = {id(it): n for n, it in enumerate(infos)}
    link_groups = {}
    for n, it in enumerate(infos):
        if do_dupes:
            link_groups.setdefault(("dup", it["sid"], it["name"].strip().lower(), it["size"]), []).append(n)
        c = _plan_norm(it["condition"])
        if do_multi and c:
            link_groups.setdefault(("cond", it["sid"], c), []).append(n)
    for members in link_groups.values():
        for m in members[1:]:
            _union(members[0], m)

    comps = {}
    for n in range(len(infos)):
        comps.setdefault(_find(n), []).append(n)
    gid = 0
    for members in comps.values():
        if len(members) > 1 and any(infos[m]["reasons"] for m in members):
            gid += 1
            for m in members:
                infos[m]["group"] = gid
                infos[m]["group_size"] = len(members)

    return sorted([it for it in infos if it["reasons"] or it.get("group")],
                  key=lambda x: (x["student"].lower(), x.get("group") or 0, x["i"]))


def apply_plan_review(plan_map, decisions):
    """
    decisions: {file key: {'action': 'keep'|'remove'|'pages', 'pages': [1-based page numbers]}}
    Edits plan_map in place. Returns (files removed, files trimmed, problems [str],
    stale = number of decisions that no longer match any current file).
    """
    removed = trimmed = matched = 0
    problems = []
    for sid in list(plan_map):
        kept = []
        for i, f in enumerate(plan_map[sid]):
            raw = _read_plan_buf(f)
            name = getattr(f, "name", "") or "attachment"
            d = decisions.get(_plan_file_key(sid, i, name, len(raw))) if raw else None
            if d:
                matched += 1
            if not d or d.get("action") == "keep":
                kept.append(f)
            elif d.get("action") == "remove":
                removed += 1
            elif d.get("action") == "pages":
                pages = sorted({int(p) for p in (d.get("pages") or [])})
                if not pages:
                    removed += 1
                    continue
                try:
                    rd = PdfReader(BytesIO(raw[_plan_pdf_offset(raw):]), strict=False)
                    wr = PdfWriter()
                    for p in pages:
                        wr.add_page(rd.pages[p - 1])
                    out = BytesIO()
                    wr.write(out)
                    nb = BytesIO(out.getvalue())
                    nb.name = name
                    nb.plan_condition = getattr(f, "plan_condition", None)
                    kept.append(nb)
                    trimmed += 1
                except Exception as e:
                    problems.append(f"{name}: couldn't keep only the selected pages ({e}) — the whole file was kept")
                    kept.append(f)
        plan_map[sid] = kept
    return removed, trimmed, problems, max(0, len(decisions) - matched)


def build_plan_map():
    """
    Collect every plan file that would go into the booklets: {student id: [BytesIO with .name]}.
    Priority per plan slot: live uploader value > cached manual upload > auto-downloaded/imported file.
    Each file is tagged with .plan_condition so several plans for one condition can be spotted.
    """
    plan_map = {}
    detected = st.session_state.get('detected_plans', {})
    auto_files = st.session_state.get("auto_downloaded_plan_files", {})
    manual_uploads = st.session_state.get("manual_plan_uploads", {})

    for sid, plans in (detected or {}).items():
        for idx, _ in enumerate(plans):
            plan_key = f"{sid}_{idx}"
            widget_key = f"plan_upload_{sid}_{idx}"
            cond = plans[idx].get("condition")

            live_file = st.session_state.get(widget_key)
            if live_file is not None:
                try:
                    live_file.seek(0)
                    raw = live_file.read()
                    if raw:
                        manual_uploads[plan_key] = (raw, live_file.name)
                        buf = BytesIO(raw)
                        buf.name = live_file.name
                        buf.plan_condition = cond
                        plan_map.setdefault(sid, []).append(buf)
                        continue
                except Exception:
                    pass

            for store in (manual_uploads, auto_files):
                if plan_key in store:
                    raw_bytes, fname = store[plan_key]
                    if raw_bytes:
                        buf = BytesIO(raw_bytes)
                        buf.name = fname
                        buf.plan_condition = cond
                        plan_map.setdefault(sid, []).append(buf)
                        break

    if "medical_plan_files" in st.session_state:
        for sid, fl in st.session_state.medical_plan_files.items():
            plan_map.setdefault(sid, [])
            for f in fl:
                plan_map[sid].append(f)

    for entry in st.session_state.get("manual_plans_store", []):
        mf = entry['file']
        if mf is not None:
            try:
                mf.seek(0)
                raw = mf.read()
                if raw:
                    buf = BytesIO(raw)
                    buf.name = getattr(mf, 'name', 'plan.pdf')
                    plan_map.setdefault(entry['sid'], []).append(buf)
            except Exception:
                pass
    return plan_map


def summarise_plan_review(decisions):
    """(files left out, files trimmed) for a saved set of review decisions."""
    removed = trimmed = 0
    for d in decisions.values():
        if d.get("action") == "remove" or (d.get("action") == "pages" and not d.get("pages")):
            removed += 1
        elif d.get("action") == "pages":
            trimmed += 1
    return removed, trimmed


def _rv_hash(it):
    import hashlib
    return hashlib.md5(it["key"].encode("utf-8")).hexdigest()[:12]


def _rv_keep_only(all_hashes, keep_hash):
    """Button callback: keep this file, leave out the other files in its group."""
    for x in all_hashes:
        st.session_state[f"rv_choice_{x}"] = "Keep" if x == keep_hash else "Remove"


def _rv_set_group(all_hashes, value):
    for x in all_hashes:
        st.session_state[f"rv_choice_{x}"] = value


def _rv_render_file_card(it, group_hashes=None, label=None):
    """One file's preview + Keep/Remove/Keep-selected-pages controls (used in groups and on its own)."""
    h = _rv_hash(it)
    if "_rv_thumbs" not in st.session_state:
        st.session_state._rv_thumbs = {}
    if "_rv_first" not in st.session_state:
        st.session_state._rv_first = {}

    if label:
        st.markdown(f"**{label}**")
    st.markdown(f"<div style='font-size:0.86rem;font-weight:600;word-break:break-all'>{it['name']}</div>", unsafe_allow_html=True)
    st.caption(f"{it['size'] / 1024:,.0f} KB · {it['pages']} page{'s' if it['pages'] != 1 else ''}")
    if it["pages"] > st.session_state.get("opt_scan_pages", 5) and st.session_state.get("opt_scan_long", True):
        st.caption(f"📄 Longer than {st.session_state.get('opt_scan_pages', 5)} pages")

    # first page, always visible, so files can be compared at a glance
    if h not in st.session_state._rv_first:
        st.session_state._rv_first[h] = plan_thumbnails(it["raw"], max_pages=1, dpi=60)
    first = st.session_state._rv_first[h]
    if first:
        st.image(first[0], use_container_width=True)

    opts = ["Keep", "Remove"]
    if it["is_pdf"] and it["pages"] > 1:
        opts.append("Keep selected pages")
    choice = st.radio("Action", opts, index=1 if it["default"] == "remove" else 0,
                      key=f"rv_choice_{h}", label_visibility="collapsed")
    if choice == "Remove":
        st.caption("🗑 Will be left out of the booklet")
    if choice == "Keep selected pages":
        st.multiselect("Pages to keep", list(range(1, it["pages"] + 1)),
                       default=list(range(1, min(it["pages"], 5) + 1)), key=f"rv_pages_{h}")
    if group_hashes and len(group_hashes) > 1:
        st.button("Keep only this one", key=f"rv_only_{h}", use_container_width=True,
                  on_click=_rv_keep_only, args=(group_hashes, h))
    if it["pages"] > 1 and st.checkbox("👁 Show all pages", key=f"rv_prev_{h}"):
        if h not in st.session_state._rv_thumbs:
            with st.spinner("Rendering pages…"):
                st.session_state._rv_thumbs[h] = plan_thumbnails(it["raw"])
        for n, tb in enumerate(st.session_state._rv_thumbs[h], 1):
            st.image(tb, caption=f"Page {n}", use_container_width=True)
        if it["pages"] > len(st.session_state._rv_thumbs[h]):
            st.caption(f"Showing the first {len(st.session_state._rv_thumbs[h])} of {it['pages']} pages.")


def render_plan_review_panel():
    """
    Review screen. Files that belong together (identical uploads / several plans for one condition) are shown
    side by side so it's easy to see which to keep; long files that aren't part of a group get a single card.
    """
    rv = st.session_state.get("_plan_review")
    if not rv:
        return
    issues = rv["issues"]
    groups, singles = {}, []
    for it in issues:
        if it.get("group"):
            groups.setdefault(it["group"], []).append(it)
        else:
            singles.append(it)

    st.markdown('<div class="section-head">Attachment review</div>', unsafe_allow_html=True)
    parts = []
    if groups:
        parts.append(f"{len(groups)} set(s) of files to compare")
    if singles:
        parts.append(f"{len(singles)} long file(s)")
    st.warning("🔎 " + " · ".join(parts) + ". Choose what to keep, then save your choices — "
               "**Generate Medical Booklet** will use them.")

    # ── Side-by-side comparison groups ───────────────────────────────────────
    for gid, members in sorted(groups.items(), key=lambda kv: (kv[1][0]["student"].lower(), kv[0])):
        n = len(members)
        hashes = [_rv_hash(m) for m in members]
        student = members[0]["student"]
        conds = sorted({m["condition"] for m in members if m.get("condition")})
        all_identical = len({(m["name"].strip().lower(), m["size"]) for m in members}) == 1
        if all_identical:
            title = f"{student} — {n} identical uploads" + (f" ({', '.join(conds)})" if conds else "")
        elif conds and len(conds) == 1:
            title = f"{student} — {n} plans for {conds[0]}"
        else:
            title = f"{student} — {n} related files" + (f" ({', '.join(conds)})" if conds else "")

        with st.container(border=True):
            st.markdown(f"**{title}**")
            if n >= 3:
                st.error(f"⚠️ {n} files are linked here — usually only the current one is needed. "
                         f"Compare them and use **Keep only this one** on the right file, or choose individually.")
            else:
                st.caption("Compare the two files below. Keep both, or keep only the right one.")
            qa1, _ = st.columns([1, 3])
            with qa1:
                st.button("Keep all", key=f"rv_all_{gid}", use_container_width=True,
                          on_click=_rv_set_group, args=(hashes, "Keep"))

            for row_start in range(0, n, 4):
                row = members[row_start:row_start + 4]
                cols = st.columns(len(row))
                for col, it in zip(cols, row):
                    with col:
                        _rv_render_file_card(it, group_hashes=hashes, label=f"File {chr(65 + members.index(it))}")

            kept = sum(1 for hh, m in zip(hashes, members)
                       if st.session_state.get(f"rv_choice_{hh}", "Remove" if m["default"] == "remove" else "Keep") != "Remove")
            st.caption(f"Keeping {kept} of {n} files")

    # ── Single long files ────────────────────────────────────────────────────
    if singles:
        st.markdown("**Long attachments**")
        for it in sorted(singles, key=lambda x: (x["student"].lower(), x["i"])):
            with st.container(border=True):
                st.markdown(f"**{it['student']}**")
                _rv_render_file_card(it)

    b1, b2, _ = st.columns([2, 1, 2])
    with b1:
        if st.button("✅ Save review choices", type="primary", key="rv_go"):
            decisions = {}
            for it in issues:
                h = _rv_hash(it)
                ch = st.session_state.get(f"rv_choice_{h}", "Remove" if it["default"] == "remove" else "Keep")
                if ch == "Remove":
                    decisions[it["key"]] = {"action": "remove"}
                elif ch == "Keep selected pages":
                    decisions[it["key"]] = {"action": "pages", "pages": st.session_state.get(f"rv_pages_{h}", [])}
                else:
                    decisions[it["key"]] = {"action": "keep"}
            st.session_state._plan_review_decisions = decisions
            st.session_state._plan_review_note = ""
            st.session_state._plan_review = None
            st.rerun()
    with b2:
        if st.button("Cancel", key="rv_cancel", help="Close the review without changing anything"):
            st.session_state._plan_review = None
            st.rerun()


def sniff_plan_bytes(data):
    """
    Work out what a downloaded plan really is from its bytes (never from its name).
    Returns (ext, clean_data, problem):
      ext        '.pdf' / '.png' / '.jpg' / '.gif' / '.webp' / '.heic' / '.docx' / '.doc' / None if unrecognised
      clean_data the bytes to save (a PDF with junk before '%PDF-' is trimmed so Preview accepts it)
      problem    None if the file looks fine, else a short human-readable reason
    """
    if not data:
        return None, data, "the download was empty"
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    low = head[:200].lower()
    if low.startswith((b"<!doctype", b"<html", b"<?xml", b"<head", b"<body")) or b"<html" in low:
        return None, data, "the server sent a web page (e.g. a login or error page) instead of a file"
    if head[:1] in (b"{", b"[") and b'"' in head[:50]:
        return None, data, "the server sent an error message instead of a file"

    idx = data[:1024].find(b"%PDF-")
    if idx != -1:
        pdf = data[idx:]
        try:
            rd = PdfReader(BytesIO(pdf), strict=False)
            if rd.is_encrypted or len(rd.pages) > 0:
                return ".pdf", pdf, None
        except Exception:
            pass
        # pypdf is stricter than the reader the booklet uses — only call it bad if pdfplumber can't open it either
        try:
            with pdfplumber.open(BytesIO(pdf)) as _p:
                if len(_p.pages) > 0:
                    return ".pdf", pdf, None
        except Exception:
            pass
        return ".pdf", pdf, "the PDF is damaged or incomplete"

    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", data, None
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg", data, None
    if data[:4] == b"GIF8":
        return ".gif", data, None
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff", data, None
    if data[:2] == b"BM":
        return ".bmp", data, None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", data, None
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heim", b"heis"):
        return ".heic", data, "this is a HEIC photo, not a PDF — it can be opened on a Mac but can't be put in the booklet"
    if data[:4] == b"PK\x03\x04":
        if b"word/" in data[:4096] or b"word/" in data[-4096:]:
            return ".docx", data, "this is a Word document, not a PDF — it can't be put in the booklet"
        return ".zip", data, "this is a ZIP/Office file, not a PDF"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".doc", data, "this is an old Word document, not a PDF — it can't be put in the booklet"
    return None, data, "the file type wasn't recognised"


def auto_download_plan(url, session_cookie, cookie_name="ASP.NET_SessionId"):
    """
    Downloads a plan and checks it is really a usable file (retrying a couple of times if the
    download came back empty, truncated or as a web page). The saved extension always matches
    the real content. Returns (BytesIO, filename, None) or (None, None, error).
    """
    import time as _time
    last_err = "Unknown error"
    for attempt in range(3):
        fobj, fname, err = _auto_download_plan_once(url, session_cookie, cookie_name)
        if fobj is None:
            last_err = err or last_err
            # Wrong/expired cookie won't fix itself on retry
            if err and ("cookie" in err.lower() or "login" in err.lower()):
                return None, None, err
            _time.sleep(0.7 * (attempt + 1))
            continue
        ext, clean, problem = sniff_plan_bytes(fobj.getvalue())
        if problem and ext in (None, ".pdf"):
            last_err = problem[0].upper() + problem[1:] + "."
            _time.sleep(0.7 * (attempt + 1))
            continue
        base = os.path.splitext(fname or "action_plan")[0] or "action_plan"
        new_name = base + (ext or os.path.splitext(fname or "")[1] or ".pdf")
        out = BytesIO(clean)
        out.name = new_name
        out.seek(0)
        return out, new_name, None
    return None, None, last_err


def _auto_download_plan_once(url, session_cookie, cookie_name="ASP.NET_SessionId"):
    """
    Attempts to download a medical action plan file from a URL using a session cookie.
    Returns: (BytesIO file object, filename, error_message)
    - On success: (BytesIO, "filename.pdf", None)
    - On failure: (None, None, "error description")
    """
    try:
        # Build cookie jar from the pasted value
        cookies = {cookie_name: session_cookie.strip()}

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/pdf,application/octet-stream,image/*,*/*"
        }

        resp = requests.get(url, cookies=cookies, headers=headers, timeout=15, allow_redirects=True)

        # Check for redirect to login page (cookie expired / invalid)
        if resp.status_code == 302 or "login" in resp.url.lower():
            return None, None, "Redirected to login — session cookie may have expired."

        if resp.status_code != 200:
            return None, None, f"Server returned status {resp.status_code}."

        content_type = resp.headers.get("Content-Type", "").lower()

        # Detect if we got an HTML page instead of a file (cookie invalid or viewer URL)
        if "text/html" in content_type:
            if "login" in resp.text.lower() or "sign in" in resp.text.lower():
                return None, None, "Session cookie invalid or expired — received login page."
            return None, None, "URL opened a web page, not a file. This link may need to be opened in a browser and downloaded manually."

        # Determine file extension from content type
        ext_map = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "application/octet-stream": ".pdf",  # assume PDF for generic binary
        }
        ext = ".pdf"  # safe default
        for mime, file_ext in ext_map.items():
            if mime in content_type:
                ext = file_ext
                break

        # Try to get filename from Content-Disposition header
        filename = None
        cd = resp.headers.get("Content-Disposition", "")
        if cd:
            fname_match = re.search(r'filename[^;=\n]*=(["\'])?(.*?)\1', cd)
            if fname_match:
                filename = fname_match.group(2).strip()

        if not filename:
            # Derive from URL
            url_path = url.split("?")[0].rstrip("/")
            filename = url_path.split("/")[-1] or f"action_plan{ext}"
            if "." not in filename:
                filename += ext

        file_bytes = BytesIO(resp.content)
        file_bytes.name = filename  # attach name so convert_file_to_images works
        file_bytes.seek(0)
        return file_bytes, filename, None

    except requests.exceptions.Timeout:
        return None, None, "Request timed out — check your network connection."
    except requests.exceptions.ConnectionError:
        return None, None, "Could not connect to the server."
    except Exception as e:
        return None, None, f"Unexpected error: {e}"


# ---------------------------------------------------------------------------
# Action-plan bulk export / import
# Saved file names look like:  12345__Smith_Jane__01_Anaphylaxis.pdf
#   <student ID>__<Surname>_<First>__<plan number>_<condition>.<ext>
# The student ID is what links a file back to its student on import; the rest is
# for humans (and as a fallback if someone renames a file and drops the ID).
# ---------------------------------------------------------------------------
_PLAN_EXTS = (".pdf", ".png", ".jpg", ".jpeg")
PLAN_FOLDER_NAME = "Action_Plans"


def _plan_slug(text, maxlen=40):
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s[:maxlen].strip("-") or "Plan"


def _plan_norm(text):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower())


def build_plan_filename(sid, surname, first, number, condition, original_name, ext=None):
    ext = ext or os.path.splitext(str(original_name or ""))[1].lower()
    if not ext or len(ext) > 6:
        ext = ".pdf"
    sid_part = re.sub(r"[^A-Za-z0-9-]", "", str(sid))
    return f"{sid_part}__{_plan_slug(surname)}_{_plan_slug(first)}__{int(number):02d}_{_plan_slug(condition)}{ext}"


def normalize_plan_to_pdf(data):
    """
    Turn whatever was downloaded into a clean PDF that opens everywhere (Preview, Acrobat, phones),
    using the same readers the booklet uses (pdfplumber for PDFs, Pillow for images).
    Returns (pdf_bytes or None, note, problem):
      note    what was done, e.g. "was a JPEG saved with a .pdf name" ('' if the file was already fine)
      problem set only when the file couldn't be turned into a PDF (pdf_bytes is then None)
    """
    ext, clean, problem = sniff_plan_bytes(data)
    note = ""

    def _images_to_pdf(images):
        images = [im.convert("RGB") for im in images]
        buf = BytesIO()
        images[0].save(buf, format="PDF", save_all=True, append_images=images[1:], resolution=150.0)
        return buf.getvalue()

    # 1) PDFs — rewrite with pypdf (rebuilds a clean header/xref table), else re-render like the booklet does
    if ext == ".pdf":
        try:
            rd = PdfReader(BytesIO(clean), strict=False)
            if rd.is_encrypted:
                rd.decrypt("")
            wr = PdfWriter()
            for pg in rd.pages:
                wr.add_page(pg)
            out = BytesIO()
            wr.write(out)
            out = out.getvalue()
            if len(PdfReader(BytesIO(out), strict=False).pages) == len(rd.pages) > 0:
                if clean != data:
                    note = "extra bytes before the PDF header were removed"
                return out, note, None
        except Exception:
            pass
        try:
            with pdfplumber.open(BytesIO(clean)) as pdf:
                ims = [pg.to_image(resolution=150).original for pg in pdf.pages]
            if ims:
                return _images_to_pdf(ims), "the PDF was damaged, so it was rebuilt from its page images", None
        except Exception:
            pass
        return None, "", problem or "the PDF could not be read"

    # 2) Images (and anything else Pillow can read) — wrap in a PDF
    try:
        im = Image.open(BytesIO(clean))
        frames = []
        try:
            from PIL import ImageSequence
            frames = [f.copy() for f in ImageSequence.Iterator(im)]
        except Exception:
            frames = [im]
        label = (ext or "image").lstrip(".").upper()
        return _images_to_pdf(frames or [im]), f"was a {label} image saved with a .pdf name — converted to PDF", None
    except Exception:
        pass

    # 3) Unknown content — last resort, the same attempt the booklet makes for files named .pdf
    try:
        with pdfplumber.open(BytesIO(clean)) as pdf:
            ims = [pg.to_image(resolution=150).original for pg in pdf.pages]
        if ims:
            return _images_to_pdf(ims), "rebuilt from page images", None
    except Exception:
        pass
    return None, "", problem or "the file type wasn't recognised"


def build_plans_zip(entries, id_to_sf):
    """
    entries: [(sid, number, condition, bytes, original_name)]
    -> (ZIP bytes containing an Action_Plans/ folder, problems [(file name, reason)], repaired [(file name, what was done)]).
    Every file is run through the same readers the booklet uses and saved as a clean PDF, so it
    opens in Preview even if the original download was mislabelled or had a quirky structure.
    A file that can't be converted is still included as-is (nothing is lost) and listed in `problems`.
    """
    buf = BytesIO()
    problems, repaired = [], []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sid, number, condition, data, orig in entries:
            surname, first = id_to_sf.get(str(sid), ("", ""))
            pdf, note, problem = normalize_plan_to_pdf(data)
            if pdf is not None:
                name = build_plan_filename(sid, surname, first, number, condition, orig, ext=".pdf")
                zf.writestr(f"{PLAN_FOLDER_NAME}/{name}", pdf)
                if note:
                    repaired.append((name, note))
            else:
                ext, clean, _ = sniff_plan_bytes(data)
                name = build_plan_filename(sid, surname, first, number, condition, orig, ext=ext or ".bin")
                zf.writestr(f"{PLAN_FOLDER_NAME}/{name}", clean)
                problems.append((name, problem or "could not be converted"))
    return buf.getvalue(), problems, repaired


def expand_plan_uploads(uploaded):
    """
    uploaded: [(name, bytes)] straight from the file uploader (loose files and/or ZIPs).
    Returns (files [(basename, bytes)], skipped [names]). ZIPs are opened; junk/hidden files and
    unsupported types are skipped.
    """
    files, skipped = [], []

    def _ok(base):
        return not base.startswith(".") and not base.startswith("~$") and os.path.splitext(base)[1].lower() in _PLAN_EXTS

    for name, data in uploaded:
        base = os.path.basename(str(name))
        if base.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(BytesIO(data)) as zf:
                    for info in zf.infolist():
                        inner = info.filename
                        b = os.path.basename(inner)
                        if info.is_dir() or "__MACOSX" in inner or not b:
                            continue
                        if _ok(b):
                            files.append((b, zf.read(info)))
                        else:
                            skipped.append(b)
            except Exception:
                skipped.append(base)
        elif _ok(base):
            files.append((base, data))
        else:
            skipped.append(base)
    return files, skipped


def link_imported_plan_files(files, detected, df, occupied=None):
    """
    Work out which student (and which plan slot) each saved file belongs to.
      1. the student ID before the first '__' in the file name
      2. any token in the file name that is a known student ID
      3. the student's name appearing in the file name (only if it identifies exactly one student)
    Slot: a detected plan whose condition matches the name -> else first empty slot -> else None
    (None = an extra plan; it's still added to that student's booklet).
    Returns (assignments [{name,data,sid,slot,condition}], unmatched [names])
    """
    occupied = set(occupied or [])
    known, name_keys = {}, {}
    for _, row in df.iterrows():
        sid = str(row[COLS["student_id"]]).strip()
        sur = row[COLS["surname"]]
        first = row[COLS["first_name"]]
        pref = row.get(COLS.get("preferred_name", "Preferred name"), "")
        known[sid] = True
        for f in {_plan_norm(first), _plan_norm(pref)} - {""}:
            for k in (_plan_norm(sur) + f, f + _plan_norm(sur)):
                name_keys.setdefault(k, set()).add(sid)

    assignments, unmatched, claimed = [], [], set()
    for name, data in files:
        stem = os.path.splitext(name)[0]
        parts = stem.split("__")
        sid = parts[0].strip() if parts[0].strip() in known else None
        if sid is None:
            hits = {t for t in re.split(r"[^A-Za-z0-9]+", stem) if t in known}
            if len(hits) == 1:
                sid = hits.pop()
        if sid is None:
            ns = _plan_norm(stem)
            hits = {s for k, ss in name_keys.items() if k and k in ns for s in ss}
            if len(hits) == 1:
                sid = hits.pop()
        if sid is None:
            unmatched.append(name)
            continue

        cond = ""
        if len(parts) >= 3:
            m = re.match(r"^\d+_(.*)$", parts[2])
            cond = m.group(1) if m else parts[2]
        nc = _plan_norm(cond)

        plans = detected.get(sid, [])
        slot = None
        if nc:
            for i, p in enumerate(plans):
                npc = _plan_norm(p.get("condition"))
                if (sid, i) not in claimed and npc and (npc == nc or npc.startswith(nc) or nc.startswith(npc)):
                    slot = i
                    break
        if slot is None:
            for i in range(len(plans)):
                if (sid, i) not in claimed and f"{sid}_{i}" not in occupied:
                    slot = i
                    break
        if slot is not None:
            claimed.add((sid, slot))
        assignments.append({"name": name, "data": data, "sid": sid, "slot": slot,
                            "condition": plans[slot]["condition"] if slot is not None else cond.replace("-", " ")})
    return assignments, unmatched


def detect_medical_plans(df):
    """
    Parses 'Medical notes' to find 'Action or medical plan links' and URLs.
    Returns: { student_id: [ {'condition': 'ALLERGIES', 'url': 'https://...', 'details': '...'} ] }
    """
    plans_needed = {}
    
    for _, row in df.iterrows():
        sid = str(row[COLS['student_id']])
        notes = str(row.get(COLS['medical_notes'], ""))
        
        if not notes: continue
        
        student_plans = []
        
        # 1. Parse specific "Action or medical plan links" section
        # We normalize whitespace to handle the split lines in your example
        clean_notes = notes.replace('\n', '').replace('\r', '')
        
        # Look for the block starting with "Action or medical plan links:" 
        # and ending at the next number or separator
        if "Action or medical plan links:" in clean_notes:
            try:
                # Extract the bit between the header and the next section (often starting with a digit like "4 Medical Conditions")
                start_marker = "Action or medical plan links:"
                start_idx = clean_notes.find(start_marker) + len(start_marker)
                
                # Find end - heuristic: look for "Medical Conditions" or "-----------"
                end_idx = len(clean_notes)
                for marker in ["Medical Conditions", "-----------"]:
                    idx = clean_notes.find(marker, start_idx)
                    if idx != -1 and idx < end_idx:
                        end_idx = idx
                
                # Get the chunk containing links
                links_chunk = clean_notes[start_idx:end_idx]
                
                # Split by ';' as per your data example
                entries = links_chunk.split(';')
                
                for entry in entries:
                    if "http" in entry:
                        # Format is usually "CONDITION: https://url"
                        # Regex to pull the name and the url
                        # Name is everything before 'http'
                        parts = entry.split('http')
                        name = parts[0].strip().strip(':').strip()
                        url = 'http' + parts[1].strip()
                        
                        student_plans.append({
                            "condition": name,
                            "url": url,
                            "details": "Link found in medical notes."
                        })
            except Exception as e:
                print(f"Error parsing plans for {sid}: {e}")

        # 2. Fallback: If no links found, check for "Action plan available" text phrases
        if not student_plans and "plan" in notes.lower():
             blocks = re.split(r'(?:Condition:|-----------)', notes)
             for block in blocks:
                 if "plan" in block.lower() and "available" in block.lower():
                     lines = block.strip().split('\n')
                     cond_name = lines[0].split('(')[0].strip()
                     if len(cond_name) > 30: cond_name = "Medical Condition"
                     
                     # Create a generic search link if no specific URL found
                     base_url = CONFIG['app_settings']['school_portal_url']
                     if base_url.endswith('/'): base_url = base_url[:-1]
                     search_link = f"{base_url}/search?id={sid}"
                     
                     student_plans.append({
                         "condition": cond_name,
                         "url": search_link, 
                         "details": block.strip()
                     })

        if student_plans:
            plans_needed[sid] = student_plans

    return plans_needed

def parse_medical_text(text):
    if not isinstance(text, str) or not text.strip(): return []
    text = text.replace('\r\n', '\n')

    # Extract "Last changed" date from the preamble (before first ---)
    last_changed = None
    lc_match = re.search(r'Last changed:\s*(\S.*)', text)
    if lc_match:
        last_changed = lc_match.group(1).strip()

    blocks = re.split(r'-{3,}', text)
    parsed_conditions = []

    for block in blocks:
        block = block.strip()
        if not block: continue
        if "Condition:" in block:
            match = re.search(r'Condition:\s*(.+?)\s*\(Severity level:\s*(.+?)\)', block)
            if match:
                cond_name = match.group(1).strip()
                severity = match.group(2).strip()
                desc_start = match.end()
                description = block[desc_start:].strip()
                
                # CSS Class determination
                css_class = "mild" 
                s_lower = severity.lower()
                
                # --- UPDATE: Force Wording "Severe/Life Threatening" ---
                if any(x in s_lower for x in ["life threatening", "severe", "anaphylaxis"]): 
                    css_class = "severe"
                    severity = "Severe/Life Threatening" # Exact wording update
                elif "moderate" in s_lower: 
                    css_class = "moderate"

                parsed_conditions.append({
                    "name": cond_name, "severity": severity, "description": description,
                    "css_class": css_class, "last_changed": last_changed
                })
    
    if not parsed_conditions and len(text) > 10 and "No data" not in text:
        parsed_conditions.append({
            "name": "General Medical Note", "severity": "Info", "description": text,
            "css_class": "mild", "last_changed": last_changed
        })
    return parsed_conditions

def detect_medical_flags(parsed_med, raw_med):
    """
    Decides which Quick Overview symbols (asthma / allergy / anaphylaxis) a
    student gets.

    Only the condition NAME and SEVERITY of each parsed condition are searched
    - not the free-text description - so a note such as "no known allergy" or
    "allergy action plan attached" under an Anaphylaxis condition can't create
    an Allergy symbol. Patterns are stems so spelling variants all match:
        asthma      -> asth...            (Asthma, Asthmatic)
        allergy     -> allerg... / hay fever / hayfever
                       (Allergy, Allergies, Allergic - the old test looked for
                        the exact word "allergy", which never matches "Allergies")
        anaphylaxis -> anaph...           (Anaphylaxis, Anaphylactic, Anaphalaxis)
    If the medical notes could not be split into named conditions (only a
    free-text "General Medical Note"), the whole text is searched instead.
    """
    named = [c for c in (parsed_med or []) if c.get('name') != 'General Medical Note']
    if named:
        haystack = ' '.join(f"{c.get('name', '')} {c.get('severity', '')}" for c in named)
    else:
        haystack = raw_med or ''
    h = haystack.lower()
    # Remove NEGATED anaphylaxis wording before searching, so that
    # "Allergies (non-anaphylactic)" counts as a plain allergy and not as
    # anaphylaxis. Covers: non-anaphylactic, non anaphylactic, nonanaphylactic,
    # not anaphylactic, no anaphylaxis, without anaphylaxis, etc.
    h_anaph = re.sub(
        r'\b(?:non|not|no|without|nil)[\s\-]*(?:known[\s\-]*)?anaph\w*',
        ' ',
        h,
    )
    return {
        'asthma':      re.search(r'asth', h) is not None,
        'allergy':     re.search(r'allerg|hay\s*-?fever', h) is not None,
        'anaphylaxis': re.search(r'anaph', h_anaph) is not None,
    }

def parse_doctors(text):
    """Parses doctor info into a structured list with map links."""
    if not isinstance(text, str) or not text.strip(): return []
    
    doctors = []
    # Split by "DOCTOR X:" or just "DOCTOR:" pattern
    entries = re.split(r'DOCTOR \d*:', text, flags=re.IGNORECASE)
    
    for entry in entries:
        entry = entry.strip()
        if not entry: continue
        
        lines = entry.split('\n')
        name = lines[0].strip()
        
        # Change default to "Not Listed"
        address = "Not Listed"
        phone = "Not Listed"
        
        for line in lines:
            if "Address:" in line:
                val = line.replace("Address:", "").strip()
                if val: address = val
            if "Telephone:" in line:
                val = line.replace("Telephone:", "").strip()
                if val: phone = val

        # Handle Map Link
        map_link = None
        if address != "Not Listed":
            map_query = urllib.parse.quote(address)
            map_link = f"https://www.google.com/maps/search/?api=1&query={map_query}"
        
        # Handle Phone Link
        phone_link = None
        if phone != "Not Listed":
            phone_clean = re.sub(r'[^0-9]', '', phone)
            if phone_clean:
                phone_link = f"tel:{phone_clean}"
        
        doctors.append({
            "name": name,
            "address": address,
            "map_link": map_link,
            "phone_display": phone,
            "phone_link": phone_link
        })
        
    return doctors

def parse_emergency_contacts(text):
    if not isinstance(text, str) or not text.strip(): return []
    contacts = []
    raw_blocks = re.split(r'EMERGENCY \d+:', text)
    
    for block in raw_blocks:
        block = block.strip()
        if not block: continue
        lines = block.split('\n')
        name = lines[0].strip()
        relation = "Unknown"
        phones = []
        for line in lines:
            if "Relationship:" in line: relation = line.split("Relationship:")[-1].strip()
            if "Telephone:" in line:
                phone_raw = line.split("Telephone:")[-1].strip()
                if phone_raw:
                    phone_clean = re.sub(r'[^\d+]', '', phone_raw)
                    phones.append({"display": phone_raw, "link": f"tel:{phone_clean}"})
        if phones: contacts.append({"name": name, "relation": relation, "phones": phones})
    return contacts

def parse_home_contacts(row):
    """
    Parses home contact information from the contact file columns.
    Returns a dictionary with contacts list and home information.
    Safely handles missing columns by returning empty values.
    """
    if not isinstance(row, pd.Series):
        return {"contacts": [], "home_address": "", "home_phone": ""}
    
    try:
        c_map = CONFIG.get('contact_file_mappings', {})
        contacts = []
        
        # Student Contact 1
        sc1_first = str(row.get(c_map.get('sc1_name_pref', 'SC1 Preferred'), '')).strip()
        sc1_last = str(row.get(c_map.get('sc1_name_sur', 'SC1 Surname'), '')).strip()
        sc1_mobile = str(row.get(c_map.get('sc1_mobile', 'SC1 Mobile'), '')).strip()
        
        # Only add if we have actual data (not just empty strings or 'nan')
        if (sc1_first and sc1_first.lower() != 'nan') or (sc1_last and sc1_last.lower() != 'nan'):
            name = f"{sc1_first} {sc1_last}".strip()
            if name and name.lower() != 'nan':  # Extra check for valid name
                phone_clean = re.sub(r'[^\d+]', '', sc1_mobile) if (sc1_mobile and sc1_mobile.lower() != 'nan') else ""
                phone_obj = {"display": sc1_mobile, "link": f"tel:{phone_clean}"} if phone_clean else None
                
                contacts.append({
                    "name": name,
                    "relation": "Student Contact 1",
                    "phone": phone_obj
                })
        
        # Student Contact 2
        sc2_first = str(row.get(c_map.get('sc2_name_pref', 'SC2 Preferred'), '')).strip()
        sc2_last = str(row.get(c_map.get('sc2_name_sur', 'SC2 Surname'), '')).strip()
        sc2_mobile = str(row.get(c_map.get('sc2_mobile', 'SC2 Mobile'), '')).strip()
        
        if (sc2_first and sc2_first.lower() != 'nan') or (sc2_last and sc2_last.lower() != 'nan'):
            name = f"{sc2_first} {sc2_last}".strip()
            if name and name.lower() != 'nan':
                phone_clean = re.sub(r'[^\d+]', '', sc2_mobile) if (sc2_mobile and sc2_mobile.lower() != 'nan') else ""
                phone_obj = {"display": sc2_mobile, "link": f"tel:{phone_clean}"} if phone_clean else None
                
                contacts.append({
                    "name": name,
                    "relation": "Student Contact 2",
                    "phone": phone_obj
                })
        
        # Home Information
        home_address = str(row.get(c_map.get('address', 'Contact Address'), '')).strip()
        home_phone = str(row.get(c_map.get('home_phone', 'Home Phone'), '')).strip()
        
        # Clean up 'nan' strings
        if home_address.lower() == 'nan':
            home_address = ""
        if home_phone.lower() == 'nan':
            home_phone = ""
        
        return {
            "contacts": contacts,
            "home_address": home_address,
            "home_phone": home_phone
        }
    except Exception as e:
        # If anything goes wrong, return empty structure
        print(f"Error parsing home contacts: {e}")
        return {"contacts": [], "home_address": "", "home_phone": ""}


# ─────────────────────────────────────────────────────────────────────────────
# SEQTA CONTACT PDF PARSER
# ─────────────────────────────────────────────────────────────────────────────

_SEQTA_LIG = {
    '\ufb00':'ff','\ufb01':'fi','\ufb02':'fl','\ufb03':'ffi','\ufb04':'ffl',
    '\ufb05':'st','\ufb06':'st','\ue000':'tt','\ue001':'ti','\ue003':'tt',
    '\u02a6':'tt','\uf001':'fi','\uf002':'fl',
}

# Placeholder for a ligature glyph we can't confidently identify (see
# _sc() below). Kept distinct from any real letter so it can be matched
# against the roster with a wildcard later, instead of guessing wrong.
_SC_UNKNOWN_CH = '\uFFFD'

def _sc(text):
    if not isinstance(text, str): return text
    for k,v in _SEQTA_LIG.items(): text = text.replace(k,v)
    out = []
    for ch in text:
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF:
            d = unicodedata.normalize('NFKD', ch)
            if d != ch:
                out.append(d)
            else:
                # Unmapped ligature glyph with no Unicode decomposition.
                # This used to be dropped entirely (out.append('')), which
                # permanently deletes a letter with no way to recover it
                # downstream (e.g. "Moretti" -> "Morett"). Guessing a fixed
                # replacement like "tt" doesn't reliably fix this either —
                # right next to a real "t" it just reproduces the same
                # deletion after de-duplication. Instead we keep a
                # placeholder marking "one or two unknown letters were
                # here"; match_seqta_contacts_app resolves it against the
                # real roster with a wildcard match instead of guessing.
                out.append(_SC_UNKNOWN_CH)
        else:
            out.append(ch)
    return unicodedata.normalize('NFC', ''.join(out))

def _sc_finalize_display(text):
    """
    Replace any leftover _SC_UNKNOWN_CH marker(s) with a plain-letter
    guess before text is shown to the user (booklet, contact lists, etc).

    A student's own surname gets a real chance at resolving the marker
    correctly first, via the wildcard match against the roster in
    match_seqta_contacts_app. But guardians/contacts have no roster of
    their own name to verify a guess against, and leaving the raw marker
    in place means the booklet shows a literal "unknown character" box
    instead of a name. "tt" is the most common ligature glyph in these
    school-system PDFs, so it's a reasonable best-effort fallback — not
    guaranteed correct, but strictly better than a visible placeholder
    symbol.
    """
    if not isinstance(text, str) or _SC_UNKNOWN_CH not in text:
        return text
    return text.replace(_SC_UNKNOWN_CH, 'tt')

_SC_STU=165; _SC_DOB=225; _SC_CON=555; _SC_YT=4
_SC_DOB_RE = re.compile(r'^\d{1,2}/\d{2}/\d{2,4}$')
_SC_GREL   = re.compile(r'^(Mother|Father|Guardian|Parent|Carer|Step|Uncle|Aunt|Grand|Relation)',re.IGNORECASE)

def _sc_col(x): 
    return 'student' if x<_SC_STU else 'dob' if x<_SC_DOB else 'contacts' if x<_SC_CON else 'medical'

def _sc_names(page):
    lines={}
    for ch in page.chars:
        if ch['x0']>=_SC_STU or not ch['text']: continue
        y=round(ch['top']/_SC_YT)*_SC_YT
        lines.setdefault(y,[]).append((ch['x0'],ch['text']))
    out={}
    for y,chars in lines.items():
        chars.sort(key=lambda c:c[0])
        t=_sc(''.join(c[1] for c in chars)).strip()
        if t: out[y]=t
    return out

def _sc_contact_lines(words):
    words=sorted(words,key=lambda w:(w['top'],w['x0']))
    lines=[]
    for w in words:
        col=_sc_col(w['x0'])
        if col not in ('dob','contacts'): continue
        t=_sc(w['text'])
        placed=False
        for line in reversed(lines):
            if abs(line['y']-w['top'])<=_SC_YT:
                line[col]=(line[col]+' '+t).strip(); placed=True; break
        if not placed:
            e={'y':w['top'],'dob':'','contacts':''}; e[col]=t; lines.append(e)
    return lines

def _sc_parse_contacts(lines):
    r={"home_address":"","home_phone":"","home_mobile":"","guardians":[]}
    af=hf=False; cur=None
    def _sv():
        if cur is not None: r["guardians"].append(cur)
    for line in lines:
        line=line.strip()
        if not line: continue
        if _SC_GREL.match(line):
            _sv()
            parts=line.split(None,1); rel=parts[0].title(); rest=parts[1].strip() if len(parts)>1 else ""
            mm=re.search(r'Mobile:\s*([\d\s\+\(\)]+)',rest,re.IGNORECASE)
            # Guardian names have no roster of their own to verify a
            # ligature-glyph guess against (unlike a student's own
            # surname), so clean up any leftover "unknown character"
            # marker here rather than let it show as a raw symbol in the
            # booklet.
            guardian_name = rest[:mm.start()].strip() if mm else rest
            cur={"relationship":_sc_finalize_display(rel),"name":_sc_finalize_display(guardian_name),
                 "mobile":mm.group(1).strip() if mm else "","home":"","work":""}
            continue
        if cur is not None and re.search(r'(?:Home:|Work:|Mobile:)',line,re.IGNORECASE):
            m=re.search(r'Mobile:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if m and not cur["mobile"]: cur["mobile"]=m.group(1).strip()
            m=re.search(r'(?<!\w)Home:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if m: cur["home"]=m.group(1).strip()
            m=re.search(r'Work:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if m: cur["work"]=m.group(1).strip()
            continue
        if not hf and re.search(r'(?<!\w)Home:',line,re.IGNORECASE):
            hm=re.search(r'(?<!\w)Home:\s*([\d\s\+\(\)]*)',line,re.IGNORECASE)
            mm=re.search(r'Mobile:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if hm: r["home_phone"]=hm.group(1).strip()
            if mm: r["home_mobile"]=mm.group(1).strip()
            hf=True; continue
        if not af:
            r["home_address"]=_sc_finalize_display(line); af=True
    _sv(); return r

def _sc_parse_name(raw):
    r={"surname":"","first_name":"","preferred":""}
    t=raw.strip()
    if not t: return r
    pm=re.search(r'\(([^)]+)\)',t); pref=pm.group(1).strip() if pm else ""
    c=re.sub(r'\([^)]*\)','',t).strip()
    if ',' in c:
        # Everything after the comma is the (possibly multi-word) first
        # name — e.g. "Frank, Ida Mai". Previously only the first token
        # was kept (".split()[0]"), silently dropping two-word first
        # names like "Ida Mai" down to just "Ida".
        p=c.split(',',1); sur=p[0].strip(); first=p[1].strip()
    else:
        tok=c.split(); sur=tok[0] if tok else ""; first=" ".join(tok[1:]) if len(tok)>1 else ""
    r["surname"]=sur; r["first_name"]=first
    # Preferred name still defaults to a single token (the colloquial
    # first name) when there's no explicit "(Preferred)" in the PDF.
    r["preferred"]=pref if pref else (first.split()[0] if first else "")
    return r

def parse_seqta_contact_pdf_app(pdf_file):
    records=[]
    if hasattr(pdf_file,"seek"): pdf_file.seek(0)
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words=page.extract_words(x_tolerance=3,y_tolerance=3)
            lines=_sc_contact_lines(words)
            names=_sc_names(page)
            anchors=[(l['y'],l['dob'].strip()) for l in lines if _SC_DOB_RE.match(l['dob'].strip())]

            # ── Carry over contact details split across a page break ──────
            # If a student's guardian/contact info runs past the bottom of
            # a page, the tail end appears at the TOP of the next page —
            # above (or on a page with) no DOB anchor of its own. Without
            # this, those lines belong to no anchor on this page and are
            # silently dropped. Re-attach them to the previous page's last
            # student record before processing this page's own anchors.
            first_anchor_y = anchors[0][0] if anchors else (page.height + 1)
            leading_clns = [l['contacts'] for l in lines if l['y'] < first_anchor_y - 2 and l['contacts']]
            if leading_clns and records:
                prev = records[-1]
                prev_clns = prev.get('_raw_contacts', '').split('\n') if prev.get('_raw_contacts') else []
                merged_clns = prev_clns + leading_clns
                prev.update(_sc_parse_contacts(merged_clns))
                prev['_raw_contacts'] = "\n".join(merged_clns)

            for idx,(dob_y,dob_val) in enumerate(anchors):
                end_y=anchors[idx+1][0] if idx+1<len(anchors) else page.height
                name_raw=''; best=999
                for y,text in names.items():
                    d=abs(y-dob_y)
                    if d<=8 and d<best and text.lower() not in ('student','dob','contacts'):
                        name_raw=text; best=d
                clns=[l['contacts'] for l in lines if l['y']>=dob_y-2 and l['y']<end_y-2 and l['contacts']]
                if not name_raw: continue
                ni=_sc_parse_name(name_raw); ci=_sc_parse_contacts(clns)
                sur=ni["surname"].strip(); first=ni["first_name"].strip()
                if not sur or (len(sur)<=2 and not first): continue
                records.append({**ni,**ci,"dob":dob_val,"_raw_name":name_raw,"_raw_contacts":"\n".join(clns)})
    return records

def match_seqta_contacts_app(pdf_records, df_students):
    id_col=COLS.get('student_id','Code'); fn_col=COLS.get('first_name','First name'); sn_col=COLS.get('surname','Surname')
    exact={}; sur_map={}
    for _,row in df_students.iterrows():
        sid=str(row.get(id_col,'')).strip(); first=str(row.get(fn_col,'')).strip().lower(); sur=str(row.get(sn_col,'')).strip().lower()
        if not sid or not sur: continue
        exact[(sur,first)]=sid; sur_map.setdefault(sur,[]).append(sid)
    matched,unmatched,ambiguous={},{},[]  # use dict for ambiguous clarity
    unmatched_list=[]

    def _lookup(sur_v, first_v, pref_v):
        """Returns (sid_or_None, ambiguous_candidates_or_None)."""
        if (sur_v,first_v) in exact: return exact[(sur_v,first_v)], None
        if pref_v and pref_v!=first_v and (sur_v,pref_v) in exact: return exact[(sur_v,pref_v)], None
        cands=sur_map.get(sur_v,[])
        if len(cands)==1: return cands[0], None
        if len(cands)>1: return None, cands
        return None, None

    def _fix_guardian_ligature(rec, correct_surname):
        """
        Guardian names come straight from the PDF text with no roster of
        their own to verify against, so the ti/tt ligature-glyph fallback
        above (which corrects the student's own surname) never reaches
        them. Guardians very often share the student's surname, so once
        we know the roster-verified correct spelling for this family, use
        it to fix a guardian name that shows the same corruption pattern.
        """
        for g in rec.get('guardians', []):
            name = g.get('name', '')
            if not name:
                continue
            fixed = name
            if correct_surname and correct_surname not in re.sub(r'[^a-z]', '', fixed.lower()):
                for pat, repl in ((r'ti', 'tt'), (r'tt', 'ti')):
                    candidate = re.sub(pat, repl, fixed)
                    if candidate != fixed and correct_surname in re.sub(r'[^a-z]', '', candidate.lower()):
                        fixed = candidate
                        break
            # Whether or not a surname-anchored fix was possible, never
            # leave a raw "unknown glyph" marker visible in the booklet —
            # the first name can be independently corrupted even when the
            # surname reads fine (there's no guardian roster to verify a
            # guess against here, so this is a best-effort fallback; see
            # _sc_finalize_display).
            fixed = _sc_finalize_display(fixed)
            if fixed != name:
                g['name'] = fixed

    for rec in pdf_records:
        sur=rec.get('surname','').strip().lower(); first=rec.get('first_name','').strip().lower(); pref=rec.get('preferred','').strip().lower()
        matched_surname = sur
        sid,cands=_lookup(sur,first,pref)
        # Keep the best "these candidates share a surname" list seen so
        # far as a fallback for the final ambiguous-review list, in case
        # none of the correction tiers below manage to fully resolve to
        # one student. A tier is only allowed to *replace* it with a
        # fresh ambiguous list if we don't already have one — reaching a
        # sibling-surname's candidate list here is not itself a failure
        # to preserve, since a *later* tier correcting the first name
        # might still narrow it down to a single sid.
        best_cands = cands

        if sid is None and _SC_UNKNOWN_CH in sur:
            # One or more ligature glyphs in the surname couldn't be
            # identified at all (see _sc()/_SC_UNKNOWN_CH) — e.g.
            # "Moretti" coming through as "More\uFFFDtt" because a
            # PDF-embedded glyph for a single "i" wasn't in our map.
            # Rather than guess a specific letter (which can easily be
            # wrong, and previously caused permanent, unrecoverable
            # deletions), resolve it by matching against the real roster:
            # each unknown glyph stands for 1-2 unknown letters, so build
            # a wildcard pattern and see if exactly one roster surname
            # fits it.
            pattern = ''.join(
                re.escape(ch) if ch != _SC_UNKNOWN_CH else '.{1,2}'
                for ch in sur
            )
            rx = re.compile('^' + pattern + '$')
            hits = [s for s in sur_map if rx.match(s)]
            if len(hits) == 1:
                sur_fixed = hits[0]
                t_sid, t_cands = _lookup(sur_fixed, first, pref)
                if t_sid is not None:
                    sid, matched_surname = t_sid, sur_fixed
                elif t_cands is not None and best_cands is None:
                    best_cands, matched_surname = t_cands, sur_fixed

        if sid is None:
            # Ligature-glyph fallback: this font's 'ti'/'tt' ligature glyphs
            # are sometimes decoded as the wrong bigram by our PDF-cleanup
            # step (e.g. "Jotic" -> "Jottc"). The corruption can go either
            # direction, so try both re-substitutions against the roster
            # rather than assuming which way it happened. The corruption
            # can land in the surname, the first name, or both — trying
            # only when the SURNAME changes (as this used to do) misses
            # cases like two siblings sharing a surname where the surname
            # already reads fine but the first name is what's corrupted
            # and needed to tell them apart, so every combination that
            # actually changed something is tried, and this also re-tries
            # even when the surname alone already matched multiple
            # siblings (an "ambiguous" result, not just "no match").
            for pat,repl in ((r'ti','tt'), (r'tt','ti')):
                sur_alt=re.sub(pat,repl,sur); first_alt=re.sub(pat,repl,first); pref_alt=re.sub(pat,repl,pref)
                if sur_alt==sur and first_alt==first and pref_alt==pref:
                    continue  # this pattern doesn't appear anywhere in the name
                for s_try, f_try, p_try in (
                    (sur_alt, first_alt, pref_alt),
                    (sur_alt, first, pref),
                    (sur, first_alt, pref_alt),
                ):
                    t_sid, t_cands = _lookup(s_try, f_try, p_try)
                    if t_sid is not None:
                        sid, matched_surname = t_sid, s_try
                        break
                    elif t_cands is not None and best_cands is None:
                        best_cands, matched_surname = t_cands, s_try
                if sid is not None:
                    break

        if sid is None and sur and _SC_UNKNOWN_CH not in sur:
            # Last-resort fuzzy fallback: covers ligature corruption the
            # tiers above can't fix (e.g. a genuinely dropped letter with
            # no marker, from characters outside the PUA range). Only
            # fires when nothing else matched, and only accepts a single,
            # close, unambiguous roster surname — this can't override or
            # interfere with any exact/ti-tt/wildcard match above.
            close = difflib.get_close_matches(sur, sur_map.keys(), n=2, cutoff=0.84)
            if len(close) == 1 and close[0] != sur:
                sur_fuzzy = close[0]
                fz_sid, fz_cands = _lookup(sur_fuzzy, first, pref)
                if fz_sid is not None:
                    sid, matched_surname = fz_sid, sur_fuzzy
                elif fz_cands is not None and best_cands is None:
                    best_cands, matched_surname = fz_cands, sur_fuzzy

        cands = None if sid is not None else best_cands
        # Whatever happens next, don't let a raw "unknown glyph" marker
        # leak into any display of the student's own PDF-extracted name
        # (e.g. the manual-matching review list) if it wasn't resolved
        # above.
        rec['surname'] = _sc_finalize_display(rec.get('surname',''))
        rec['first_name'] = _sc_finalize_display(rec.get('first_name',''))
        rec['preferred'] = _sc_finalize_display(rec.get('preferred',''))
        if cands:
            ambiguous.append((rec,cands)); continue
        if sid:
            _fix_guardian_ligature(rec, matched_surname)
            matched[sid]=rec
        else:
            _fix_guardian_ligature(rec, '')
            unmatched_list.append(rec)
    return matched, unmatched_list, ambiguous

def home_contacts_from_pdf(pdf_rec):
    if not pdf_rec: return {"contacts":[],"home_address":"","home_phone":""}
    contacts=[]
    for g in pdf_rec.get("guardians",[]):
        ph=g.get("mobile") or g.get("home") or ""
        pc=re.sub(r'[^\d+]','',ph)
        po={"display":ph,"link":f"tel:{pc}"} if pc else None
        n=g.get("name","").strip()
        if n: contacts.append({"name":n,"relation":g.get("relationship","Guardian"),"phone":po})
    hp=pdf_rec.get("home_phone","") or pdf_rec.get("home_mobile","")
    return {"contacts":contacts,"home_address":pdf_rec.get("home_address",""),"home_phone":hp}


def parse_emergency_contact_names(emergency_text):
    """
    Extracts names from emergency contact text in Student List CSV.
    Returns list of full names (first + last) in lowercase.
    
    Example input:
    "EMERGENCY 1: Jessica Gray
    Relationship: Mother
    Telephone: 0400 765 567
    
    EMERGENCY 2: George Gray
    Relationship: Father"
    
    Returns: ["jessica gray", "george gray"]
    """
    if not isinstance(emergency_text, str):
        return []
    
    names = []
    # Find all "EMERGENCY X: Name" patterns
    # Updated regex to only capture non-empty names (at least one word character)
    pattern = r'EMERGENCY \d+:\s*([A-Za-z][A-Za-z\s\-\']+?)(?:\n|$)'
    matches = re.findall(pattern, emergency_text)
    
    for name in matches:
        name = name.strip()
        # Additional validation: must have at least 2 characters and not be just whitespace
        if name and len(name) >= 2 and name.lower() not in ['not supplied', 'relationship:', 'telephone:']:
            # Convert to lowercase for matching
            names.append(name.lower())
    
    return names

def _build_parent_surname_lookup(contact_df):
    """
    Given the contact/attendance dataframe (already merged), build a dict:
        { parent_surname_lower: [ {sid, first_lower}, ... ] }
    using SC1/SC2 Preferred + Surname columns.
    Each entry stores both the student ID and the parent's first name so
    callers can require a first-name match, not just a surname match.
    Returns an empty dict if contact_df is None or columns are missing.
    """
    lookup = {}  # surname_lower -> list of {sid, first}
    if contact_df is None:
        return lookup

    c_map    = CONFIG.get('contact_file_mappings', {})
    id_col   = c_map.get('join_key', 'ID')
    sc1_sur  = c_map.get('sc1_name_sur',  'SC1 Surname')
    sc2_sur  = c_map.get('sc2_name_sur',  'SC2 Surname')
    sc1_pref = c_map.get('sc1_name_pref', 'SC1 Preferred')
    sc2_pref = c_map.get('sc2_name_pref', 'SC2 Preferred')

    for _, row in contact_df.iterrows():
        sid = str(row.get(id_col, '')).strip()
        if not sid:
            continue
        for sur_col, first_col in [(sc1_sur, sc1_pref), (sc2_sur, sc2_pref)]:
            sur   = str(row.get(sur_col,   '')).strip().lower()
            first = str(row.get(first_col, '')).strip().lower()
            if sur and sur not in ('nan', ''):
                lookup.setdefault(sur, [])
                # Avoid duplicate entries for the same sid+first
                entry = {'sid': sid, 'first': first}
                if entry not in lookup[sur]:
                    lookup[sur].append(entry)

    return lookup


def _build_parent_lookup_from_pdf(seqta_matched):
    """
    Build parent surname lookup from Seqta PDF guardian data.
    seqta_matched: { student_id: pdf_record } where each record has 'guardians'
    list of { name: "Firstname Lastname", relationship, mobile... }
    Returns: { surname_lower: [ {sid, first_lower}, ... ] }
    """
    lookup = {}
    if not seqta_matched:
        return lookup
    for sid, rec in seqta_matched.items():
        for guardian in rec.get('guardians', []):
            full_name = guardian.get('name', '').strip()
            if not full_name:
                continue
            parts = full_name.split()
            if len(parts) < 2:
                continue
            surname = parts[-1].lower()
            first   = parts[0].lower()
            entry   = {'sid': sid, 'first': first}
            lookup.setdefault(surname, [])
            if entry not in lookup[surname]:
                lookup[surname].append(entry)
    return lookup


def _read_and_dedup_csv(file_obj):
    """
    Reads a Paperly-format CSV and deduplicates rows by email, keeping the most
    recent submission.  Finds Email and Submission Time by column name rather than
    position so that extra columns (e.g. User Group Status) don't shift the index.
    Returns the cleaned DataFrame.
    """
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    df = pd.read_csv(file_obj).fillna("")

    # Find by name — robust to extra columns being inserted at any position
    col_email = next((c for c in df.columns if c.lower() == 'email'), df.columns[0])
    col_time  = next((c for c in df.columns if 'submission time' in c.lower()), None)

    if col_time is None:
        # No time column — just deduplicate by email without sorting
        has_email = df[df[col_email].astype(str).str.strip() != ""]
        no_email  = df[df[col_email].astype(str).str.strip() == ""]
        deduped = has_email.drop_duplicates(subset=[col_email], keep='first')
        return pd.concat([deduped, no_email], ignore_index=True)

    df[col_time] = pd.to_datetime(df[col_time], errors='coerce')
    has_email = df[df[col_email].astype(str).str.strip() != ""]
    no_email  = df[df[col_email].astype(str).str.strip() == ""]
    deduped = (
        has_email
        .sort_values(col_time, ascending=False)
        .drop_duplicates(subset=[col_email], keep='first')
    )
    return pd.concat([deduped, no_email], ignore_index=True)

def collate_csvs(file_list):
    """
    Accepts a list of Streamlit UploadedFile objects (all CSVs with the same
    column structure) and concatenates them into a single BytesIO object that
    looks identical to one uploaded file.  This lets the existing matching
    functions work completely unchanged whether the user uploads one file or ten.

    Deduplication is handled later inside each matching function (by email +
    Submission Time), so simple concatenation here is safe.

    Returns a BytesIO on success, or None if file_list is empty/None.
    """
    if not file_list:
        return None

    frames = []
    header = None

    for f in file_list:
        try:
            if hasattr(f, 'seek'):
                f.seek(0)
            df = pd.read_csv(f)
            if header is None:
                header = list(df.columns)
            frames.append(df)
        except Exception as e:
            print(f"[collate_csvs] Could not read '{getattr(f, 'name', '?')}': {e}")

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    buf = BytesIO()
    combined.to_csv(buf, index=False)
    buf.seek(0)
    buf.name = "collated.csv"   # give it a .name so downstream code is happy
    return buf


def match_swimming_ability(df_main, swimming_csv, contact_df=None):
    """
    Matches swimming ability to students by searching for the student's surname
    within the 'Student' column of the swimming CSV.

    CSV format (7 cols, 6 headers — Email used as implicit index by pandas):
      Email, First Name, Surname, Student, Submission Time, [Status], Swimming Ability

    Read with explicit column names to avoid the index-shift problem.

    Strategy:
    - Unique surname  → match if surname appears as a whole word in Student field
    - Duplicate surnames → require surname + first/preferred name both present
    - Deduplicates by email, keeping the most recent submission
    """
    if swimming_csv is None:
        print("\n⚠️  No swimming CSV provided - skipping")
        return {}, []

    try:
        if hasattr(swimming_csv, 'seek'):
            swimming_csv.seek(0)

        # Read with actual headers — don't hardcode column positions.
        # The Paperly form export added a "User Group Status" column between
        # "Status" and "Swimming Ability", pushing ability to index 7.
        # Reading real headers makes this robust to future column additions.
        swim_df = pd.read_csv(swimming_csv).fillna("")

        print(f"\n{'='*80}")
        print("SWIMMING ABILITY MATCHING")
        print(f"{'='*80}")
        print(f"Columns found: {list(swim_df.columns)}")
        print(f"Total rows: {len(swim_df)}")

        # ── Locate the student name column ────────────────────────────────────
        student_col = None
        for _candidate in ['Student', 'student', 'Student Name', 'StudentName']:
            if _candidate in swim_df.columns:
                student_col = _candidate
                break
        if student_col is None:
            for _c in swim_df.columns:
                if 'student' in _c.lower():
                    student_col = _c
                    break
        if student_col is None:
            st.error("Swimming CSV: could not find a 'Student' column. "
                     f"Columns present: {list(swim_df.columns)}")
            return {}, []

        # ── Locate the swimming ability column ────────────────────────────────
        ability_col = None
        for _candidate in ['Swimming Ability', 'swimming ability', 'SwimmingAbility',
                           'Ability', 'ability', 'Swimming']:
            if _candidate in swim_df.columns:
                ability_col = _candidate
                break
        if ability_col is None:
            for _c in swim_df.columns:
                if 'swim' in _c.lower() or 'ability' in _c.lower():
                    ability_col = _c
                    break
        # Last-resort: use the final column (old format had it unnamed at the end)
        if ability_col is None:
            ability_col = swim_df.columns[-1]
            print(f"Warning: could not find ability column by name — using last column: '{ability_col}'")

        print(f"Using student column: '{student_col}', ability column: '{ability_col}'")

        # Deduplicate by email, keep most recent
        swim_df['_time'] = pd.to_datetime(swim_df['Submission Time'], errors='coerce')
        has_email = swim_df[swim_df['Email'].str.strip() != ""]
        no_email  = swim_df[swim_df['Email'].str.strip() == ""]
        deduped = has_email.sort_values('_time', ascending=False).drop_duplicates(subset=['Email'], keep='first')
        swim_df = pd.concat([deduped, no_email], ignore_index=True)
        print(f"Rows after dedup: {len(swim_df)}")

        # Identify duplicate student surnames in the main list
        surname_counts = {}
        for _, row in df_main.iterrows():
            s = str(row[COLS['surname']]).strip().lower()
            if s:
                surname_counts[s] = surname_counts.get(s, 0) + 1
        duplicate_surnames = {s for s, c in surname_counts.items() if c > 1}
        print(f"Duplicate surnames in student list: {len(duplicate_surnames)}")

        matched = {}
        unmatched = []
        used_indices = set()
        matched_count = 0

        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")

        for _, student_row in df_main.iterrows():
            student_id     = str(student_row[COLS['student_id']])
            first_name     = str(student_row[COLS['first_name']]).strip()
            preferred_name = str(student_row.get('Preferred name', '')).strip()
            surname        = str(student_row[COLS['surname']]).strip()

            if not surname:
                continue

            surname_lower = surname.lower()
            first_lower   = first_name.lower()
            pref_lower    = preferred_name.lower()
            has_dup       = surname_lower in duplicate_surnames

            match_found = False
            for swim_idx, swim_row in swim_df.iterrows():
                if swim_idx in used_indices:
                    continue

                student_name_field = str(swim_row.get(student_col, '')).strip().lower()
                ability = str(swim_row.get(ability_col, '')).strip()

                if not ability or ability.lower() in ('nan', 'submitted', ''):
                    continue

                surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'

                if not has_dup:
                    if re.search(surname_pattern, student_name_field):
                        matched[student_id] = ability
                        used_indices.add(swim_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{swim_row[student_col]}' : {ability}")
                        break
                else:
                    surname_match = re.search(surname_pattern, student_name_field)
                    first_match   = re.search(r'\b' + re.escape(first_lower) + r'\b', student_name_field) if first_lower else None
                    pref_match    = re.search(r'\b' + re.escape(pref_lower)  + r'\b', student_name_field) if pref_lower  else None
                    if surname_match and (first_match or pref_match):
                        matched[student_id] = ability
                        used_indices.add(swim_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{swim_row[student_col]}' : {ability}")
                        break

            if not match_found and matched_count <= 10:
                print(f"[ ] ✗ {surname}, {first_name} (ID: {student_id}) — not found in swimming CSV")

        # Collect unmatched swimming rows for manual assignment
        for swim_idx, swim_row in swim_df.iterrows():
            if swim_idx not in used_indices:
                student_name = str(swim_row.get(student_col, '')).strip()
                ability = str(swim_row.get(ability_col, '')).strip()
                if student_name and ability and ability.lower() not in ('nan', 'submitted', ''):
                    unmatched.append({'student_name': student_name, 'ability': ability, 'index': swim_idx})

        print(f"\n✓ Matched: {len(matched)}  ✗ Unmatched rows: {len(unmatched)}")
        print(f"{'='*80}\n")
        return matched, unmatched

    except Exception as e:
        st.error(f"Error processing swimming CSV: {e}")
        import traceback
        print(traceback.format_exc())
        return {}, []

def get_swimming_display_color(ability):
    """
    Returns color class based on swimming ability.
    """
    if not ability or ability.lower() == 'data not recorded':
        return 'swim-none'
    elif 'cannot swim' in ability.lower():
        return 'swim-cannot'
    elif 'weak swimmer' in ability.lower():
        return 'swim-weak'
    else:
        return 'swim-ok'

def match_dietary_requirements(df_main, dietary_csv, contact_csv=None):
    """
    Matches dietary requirements to students by searching for the student's surname
    within the 'Student' column of the dietary CSV.

    Strategy:
    - Unique surname  → match if surname appears as a whole word in Student field
    - Duplicate surnames → require surname + first/preferred name both present
    - Deduplicates by email, keeping the most recent submission
    """
    try:
        if hasattr(dietary_csv, 'seek'):
            dietary_csv.seek(0)

        # Read with actual headers — don't hardcode column positions.
        # Paperly forms may gain extra columns (e.g. "User Group Status") between
        # known fields, which shifts positional indices and silently maps the wrong
        # data. Reading real headers and finding columns by name is robust to this.
        dietary_df = pd.read_csv(dietary_csv).fillna("")

        print(f"\n{'='*80}")
        print("DIETARY REQUIREMENTS MATCHING")
        print(f"{'='*80}")
        print(f"Columns found: {list(dietary_df.columns)}")
        print(f"Total rows: {len(dietary_df)}")

        # ── Locate the student name column ────────────────────────────────────
        student_col = None
        for _candidate in ['Student', 'student', 'Student Name']:
            if _candidate in dietary_df.columns:
                student_col = _candidate
                break
        if student_col is None:
            for _c in dietary_df.columns:
                if 'student' in _c.lower():
                    student_col = _c
                    break
        if student_col is None:
            st.error("Dietary CSV: could not find a 'Student' column. "
                     f"Columns present: {list(dietary_df.columns)}")
            return {}, []

        # ── Locate the dietary requirements column ────────────────────────────
        dietary_col = None
        for _candidate in ['Dietary Requirements', 'dietary requirements',
                           'DietaryRequirements', 'Dietary', 'dietary']:
            if _candidate in dietary_df.columns:
                dietary_col = _candidate
                break
        if dietary_col is None:
            for _c in dietary_df.columns:
                if 'dietary' in _c.lower() or 'requirement' in _c.lower():
                    dietary_col = _c
                    break
        if dietary_col is None:
            st.error("Dietary CSV: could not find a 'Dietary Requirements' column. "
                     f"Columns present: {list(dietary_df.columns)}")
            return {}, []

        print(f"Using student column: '{student_col}', dietary column: '{dietary_col}'")

        # ── Deduplicate by email, keep most recent ────────────────────────────
        _email_col = next((c for c in dietary_df.columns if c.lower() == 'email'), None)
        _time_col  = next((c for c in dietary_df.columns if 'submission time' in c.lower()), None)
        if _email_col and _time_col:
            dietary_df['_time'] = pd.to_datetime(dietary_df[_time_col], errors='coerce')
            has_email = dietary_df[dietary_df[_email_col].str.strip() != ""]
            no_email  = dietary_df[dietary_df[_email_col].str.strip() == ""]
            deduped = has_email.sort_values('_time', ascending=False).drop_duplicates(subset=[_email_col], keep='first')
            dietary_df = pd.concat([deduped, no_email], ignore_index=True)
        print(f"Rows after dedup: {len(dietary_df)}")

        # Identify duplicate student surnames
        surname_counts = {}
        for _, row in df_main.iterrows():
            s = str(row[COLS['surname']]).strip().lower()
            if s:
                surname_counts[s] = surname_counts.get(s, 0) + 1
        duplicate_surnames = {s for s, c in surname_counts.items() if c > 1}
        print(f"Duplicate surnames in student list: {len(duplicate_surnames)}")

        matched = {}
        unmatched = []
        used_indices = set()
        matched_count = 0

        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")

        for _, student_row in df_main.iterrows():
            student_id     = str(student_row[COLS['student_id']])
            first_name     = str(student_row[COLS['first_name']]).strip()
            preferred_name = str(student_row.get('Preferred name', '')).strip()
            surname        = str(student_row[COLS['surname']]).strip()

            if not surname:
                continue

            surname_lower = surname.lower()
            first_lower   = first_name.lower()
            pref_lower    = preferred_name.lower()
            has_dup       = surname_lower in duplicate_surnames

            match_found = False
            for diet_idx, diet_row in dietary_df.iterrows():
                if diet_idx in used_indices:
                    continue

                student_name_field = str(diet_row.get(student_col, '')).strip().lower()
                dietary_req = str(diet_row.get(dietary_col, '')).strip()

                # Normalise empty / nil / N/A
                if not dietary_req or dietary_req.lower() in ('nan', 'submitted', '', 'nil', 'n/a'):
                    dietary_req = "No concerns listed"

                surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'

                if not has_dup:
                    if re.search(surname_pattern, student_name_field):
                        matched[student_id] = dietary_req
                        used_indices.add(diet_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{diet_row[student_col]}' : {dietary_req[:50]}...")
                        break
                else:
                    surname_match = re.search(surname_pattern, student_name_field)
                    first_match   = re.search(r'\b' + re.escape(first_lower) + r'\b', student_name_field) if first_lower else None
                    pref_match    = re.search(r'\b' + re.escape(pref_lower)  + r'\b', student_name_field) if pref_lower  else None
                    if surname_match and (first_match or pref_match):
                        matched[student_id] = dietary_req
                        used_indices.add(diet_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{diet_row[student_col]}' : {dietary_req[:50]}...")
                        break

            if not match_found and matched_count <= 10:
                print(f"[ ] ✗ {surname}, {first_name} (ID: {student_id}) — not found in dietary CSV")

        # Collect unmatched dietary rows for manual assignment
        for diet_idx, diet_row in dietary_df.iterrows():
            if diet_idx not in used_indices:
                student_name = str(diet_row.get(student_col, '')).strip()
                dietary_req  = str(diet_row.get(dietary_col, '')).strip()
                if not dietary_req or dietary_req.lower() in ('nan', 'submitted', '', 'nil', 'n/a'):
                    dietary_req = "No concerns listed"
                if student_name:
                    unmatched.append({'student_name': student_name, 'dietary_req': dietary_req, 'index': diet_idx})

        print(f"\n✓ Matched: {len(matched)}  ✗ Unmatched rows: {len(unmatched)}")
        print(f"{'='*80}\n")
        return matched, unmatched

    except Exception as e:
        st.error(f"Error processing dietary CSV: {e}")
        import traceback
        print(traceback.format_exc())
        return {}, []

def parse_camp_medication_csv(camp_csv):
    """
    Parses the camp medication Paperly form CSV.
    Expects columns:  Email, First Name, Surname, Student, Submission Time, Status,
                      'Does your child require any medication…',
                      'Please describe the medication required (medication 1)',
                      'Is there any additional medication…',
                      'Please describe the medication required (medication 2)',
                      …repeating up to medication 10…,
                      'Is there any more medication…',
                      'Please describe the remainder of the medication required…',
                      plus three standing OTC-medication permission questions
                      (Antihistamines / Ibuprofen / Paracetamol), answered
                      "Yes, I approve" or "No, I do not approve".

    Returns a dict:
        { student_name_lower: {
            'display_name': str,
            'medications': [str],       # empty if student doesn't need camp meds
            'permissions': {
                'antihistamine': True/False/None,
                'ibuprofen':     True/False/None,
                'paracetamol':   True/False/None,
            }
        } }
    Includes every student who submitted the form (not just those needing
    camp medication) so the OTC permission answers are captured for everyone.
    Deduplicates by email, keeping the most-recent submission.
    """
    try:
        if hasattr(camp_csv, 'seek'):
            camp_csv.seek(0)

        df = pd.read_csv(camp_csv).fillna("")

        # Deduplicate by email (keep most-recent)
        if 'Email' in df.columns and 'Submission Time' in df.columns:
            df['_time'] = pd.to_datetime(df['Submission Time'], errors='coerce')
            has_email = df[df['Email'].str.strip() != ""]
            no_email  = df[df['Email'].str.strip() == ""]
            deduped = (has_email
                       .sort_values('_time', ascending=False)
                       .drop_duplicates(subset=['Email'], keep='first'))
            df = pd.concat([deduped, no_email], ignore_index=True)

        # Find the "needs medication" column (may legitimately be absent on
        # older exports — we still want to capture the permission questions)
        needs_col = next(
            (c for c in df.columns if 'require any medication' in c.lower()), None
        )

        # All medication *description* columns (in order they appear)
        desc_cols = [
            c for c in df.columns
            if 'describe the medication' in c.lower()
            or 'remainder of the medication' in c.lower()
        ]

        # Standing OTC-medication permission columns
        antihist_col    = next((c for c in df.columns if 'antihistamine' in c.lower()), None)
        ibuprofen_col   = next((c for c in df.columns if 'ibuprofen'   in c.lower()), None)
        paracetamol_col = next((c for c in df.columns if 'paracetamol' in c.lower()), None)

        def _perm_val(row, col):
            if not col:
                return None
            v = str(row.get(col, '')).strip().lower()
            if v.startswith('yes'):
                return True
            if v.startswith('no'):
                return False
            return None

        result = {}
        for _, row in df.iterrows():
            student_name = str(row.get('Student', '')).strip()
            if not student_name or student_name.lower() == 'nan':
                continue

            medications = []
            if needs_col is not None and str(row[needs_col]).strip().lower() == 'yes':
                medications = [
                    str(row[c]).strip()
                    for c in desc_cols
                    if str(row[c]).strip() and str(row[c]).strip().lower() != 'nan'
                ]

            permissions = {
                'antihistamine': _perm_val(row, antihist_col),
                'ibuprofen':     _perm_val(row, ibuprofen_col),
                'paracetamol':   _perm_val(row, paracetamol_col),
            }

            key = student_name.lower()
            if key in result:
                # Same student submitted twice after dedup — shouldn't normally happen
                result[key]['medications'].extend(medications)
            else:
                result[key] = {
                    'display_name': student_name,
                    'medications': medications,
                    'permissions': permissions,
                }

        n_needs_meds = sum(1 for v in result.values() if v['medications'])
        print(f"[Camp Meds] Parsed {len(result)} submissions ({n_needs_meds} needing medication).")
        return result

    except Exception as e:
        print(f"[Camp Meds] parse_camp_medication_csv error: {e}")
        import traceback; print(traceback.format_exc())
        return {}


def _match_camp_submissions_to_students(df_main, camp_data):
    """
    Shared surname + first/preferred-name matching between camp CSV
    submissions (keyed by lowercase 'Student' name) and the main student
    list. Used by both the medication log matcher and the OTC-permission
    matcher so the two stay consistent.

    Returns:
        matched   = { student_id: {**camp_data value, 'name': str} }
        unmatched = [ {**camp_data value, 'index': key} ]
    """
    if not camp_data:
        return {}, []

    # Build duplicate-surname set
    surname_counts = {}
    for _, row in df_main.iterrows():
        s = str(row[COLS['surname']]).strip().lower()
        if s:
            surname_counts[s] = surname_counts.get(s, 0) + 1
    duplicate_surnames = {s for s, c in surname_counts.items() if c > 1}

    matched   = {}
    used_keys = set()

    for _, student_row in df_main.iterrows():
        student_id     = str(student_row[COLS['student_id']])
        first_name     = str(student_row[COLS['first_name']]).strip()
        preferred_name = str(student_row.get('Preferred name', '')).strip()
        surname        = str(student_row[COLS['surname']]).strip()

        if not surname:
            continue

        surname_lower = surname.lower()
        first_lower   = first_name.lower()
        pref_lower    = preferred_name.lower()
        has_dup       = surname_lower in duplicate_surnames

        surname_pat = re.compile(r'\b' + re.escape(surname_lower) + r'\b')

        for key, data in camp_data.items():
            if key in used_keys:
                continue
            if not has_dup:
                if surname_pat.search(key):
                    matched[student_id] = dict(data, name=f"{preferred_name or first_name} {surname}")
                    used_keys.add(key)
                    break
            else:
                if surname_pat.search(key):
                    first_pat = re.compile(r'\b' + re.escape(first_lower) + r'\b') if first_lower else None
                    pref_pat  = re.compile(r'\b' + re.escape(pref_lower)  + r'\b') if pref_lower  else None
                    if (first_pat and first_pat.search(key)) or (pref_pat and pref_pat.search(key)):
                        matched[student_id] = dict(data, name=f"{preferred_name or first_name} {surname}")
                        used_keys.add(key)
                        break

    unmatched = [dict(v, index=k) for k, v in camp_data.items() if k not in used_keys]
    return matched, unmatched


def match_camp_medications(df_main, camp_csv):
    """
    Matches parsed camp medication data to student IDs in df_main.
    Only carries forward students who actually need camp medication (for
    the medication administration log page). Uses surname-first matching.

    Returns:
        matched   = { student_id: { 'name': str, 'medications': [str] } }
        unmatched = [ { 'student_name': str, 'medications': [str], 'index': key } ]
    """
    camp_data = parse_camp_medication_csv(camp_csv)
    meds_data = {k: v for k, v in camp_data.items() if v['medications']}

    all_matched, all_unmatched = _match_camp_submissions_to_students(df_main, meds_data)

    matched = {
        sid: {'name': v['name'], 'medications': v['medications']}
        for sid, v in all_matched.items()
    }
    unmatched = [
        {'student_name': v['display_name'], 'medications': v['medications'], 'index': v['index']}
        for v in all_unmatched
    ]

    print(f"[Camp Meds] Matched: {len(matched)}  Unmatched: {len(unmatched)}")
    return matched, unmatched


def match_camp_permissions(df_main, camp_csv):
    """
    Matches the three standing OTC-medication permission answers
    (Antihistamine / Ibuprofen / Paracetamol) from the camp medication CSV
    to student IDs — covers every student who submitted the form, regardless
    of whether they need camp medication. Uses the same surname-first
    matching strategy as match_camp_medications.

    Returns:
        { student_id: { 'antihistamine': True/False/None,
                         'ibuprofen': True/False/None,
                         'paracetamol': True/False/None } }
    """
    camp_data = parse_camp_medication_csv(camp_csv)
    all_matched, _ = _match_camp_submissions_to_students(df_main, camp_data)
    return {sid: v['permissions'] for sid, v in all_matched.items()}


def match_photo_permissions(df_main, photo_perm_csv):
    """
    Matches photo permission responses to students using a three-tier strategy:

    Tier 1 — Emergency contacts from the student list CSV.
             Matches the parent's first name AND surname (both required as
             whole words) against names parsed from each student's Emergency
             Notes field. Works with no optional files uploaded.
    Tier 2 — Contact CSV SC1/SC2 Surname lookup (if Attendance CSV uploaded).

    No surname-only fallback is used — parent name must explicitly appear
    in a student's emergency contacts or contact CSV to count as a match.
    Students with no match are marked 'No Response'.

    A student is 'Yes' only if BOTH questions are answered 'Yes'.
    Any 'No' answer → 'No'. No match found → 'No Response'.

    CSV format: Email, First Name, Surname, Submission Time, Status, Q1, Q2
    """
    try:
        df = _read_and_dedup_csv(photo_perm_csv)

        # Find name columns by header rather than position
        col_first   = next((c for c in df.columns if c.lower() == 'first name'), df.columns[1])
        col_surname = next((c for c in df.columns if c.lower() == 'surname'), df.columns[2])
        # Question columns are always the last two in Paperly forms, regardless of
        # how many metadata columns (Status, User Group Status, etc.) precede them
        q_cols      = [df.columns[-2], df.columns[-1]]

        print(f"\n{'='*80}")
        print("PHOTO PERMISSIONS MATCHING")
        print(f"{'='*80}")
        print(f"Columns: {list(df.columns)}")
        print(f"Rows (after dedup): {len(df)}")
        print(f"  Q1: '{q_cols[0]}'")
        print(f"  Q2: '{q_cols[1]}'")

        # ── Build permission records list: [{first, surname, result}] ─────
        # Store each parent as separate fields so we can match first AND last
        # independently against emergency contact names.
        perm_records = []
        for _, row in df.iterrows():
            p_first   = str(row[col_first]).strip().lower()
            p_surname = str(row[col_surname]).strip().lower()
            q1 = str(row[q_cols[0]]).strip().lower()
            q2 = str(row[q_cols[1]]).strip().lower()
            result = 'Yes' if (q1 == 'yes' and q2 == 'yes') else 'No'
            if p_first and p_surname:
                perm_records.append({'first': p_first, 'surname': p_surname, 'result': result})

        def _name_matches_perm(emerg_name_lower, perm):
            """
            Returns True if the permission record's first name AND surname
            both appear as whole words within the emergency contact name string.
            Handles middle names and any word order.
            e.g. emerg_name = "jessica anne gray"
                 perm first="jessica" surname="gray" → True
                 perm first="jessica" surname="smith" → False
            """
            first_pat   = r'\b' + re.escape(perm['first'])   + r'\b'
            surname_pat = r'\b' + re.escape(perm['surname']) + r'\b'
            return (re.search(first_pat, emerg_name_lower) is not None and
                    re.search(surname_pat, emerg_name_lower) is not None)

        # ── Tier 2 prep: guardian lookup from Seqta PDF (incl. manual matches) ─
        seqta_matched = st.session_state.get('seqta_contact_matched', {}).copy()
        # Include manually matched students so their guardians are also checked
        seqta_manual    = st.session_state.get('seqta_contact_manual', {})
        seqta_unmatched = st.session_state.get('seqta_contact_unmatched', [])
        for idx, msid in seqta_manual.items():
            for rec in seqta_unmatched:
                if rec.get('_index') == idx:
                    seqta_matched[msid] = rec
                    break
        if seqta_matched:
            parent_lookup = _build_parent_lookup_from_pdf(seqta_matched)
            source_label  = "Seqta PDF guardians"
        else:
            # Fallback to old attendance CSV for backward compatibility
            contact_df    = st.session_state.get('contact_csv_df', None)
            parent_lookup = _build_parent_surname_lookup(contact_df)
            source_label  = "Attendance CSV (SC1/SC2)"
        using_contact = bool(parent_lookup)
        print(f"Emergency contacts: always active (first + last name required)")
        print(f"Parent lookup ({source_label}): {using_contact} ({len(parent_lookup)} surnames indexed)")

        # ── Tier 3 prep: student own-surname lookup ───────────────────────────
        student_surname_lookup = {}
        for _, row in df_main.iterrows():
            sid   = str(row[COLS['student_id']])
            sname = str(row[COLS['surname']]).strip().lower()
            if sname:
                student_surname_lookup.setdefault(sname, set()).add(sid)

        # ── Start every student as No Response ───────────────────────────────
        permissions = {str(row[COLS['student_id']]): 'No Response' for _, row in df_main.iterrows()}

        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")

        for _, student_row in df_main.iterrows():
            sid = str(student_row[COLS['student_id']])

            # Collect ALL confirmed matches for this student across all tiers.
            # A confirmed match means the parent name was explicitly found in
            # this student's emergency contacts or contact CSV — not just a
            # surname coincidence with an unrelated person.
            # "No wins" only among confirmed matches for the same student.
            confirmed_matches = []  # list of (result, tier_description)

            # ── Tier 1: match parent first + last name against emergency contacts
            emerg_text  = str(student_row.get(COLS['emergency_notes'], '')).strip()
            emerg_names = parse_emergency_contact_names(emerg_text)

            # Build the student's own name variants to exclude self-matches.
            # A student's own name should never be treated as an emergency contact.
            s_first     = str(student_row[COLS['first_name']]).strip().lower()
            s_pref      = str(student_row.get('Preferred name', '')).strip().lower()
            s_surname   = str(student_row[COLS['surname']]).strip().lower()

            for emerg_name in emerg_names:
                # Skip if this emergency contact name is the student themselves
                emerg_parts = emerg_name.split()
                if len(emerg_parts) >= 2:
                    emerg_first   = emerg_parts[0]
                    emerg_surname = emerg_parts[-1]
                    is_student = (
                        emerg_surname == s_surname and
                        (emerg_first == s_first or (s_pref and emerg_first == s_pref))
                    )
                    if is_student:
                        print(f"  [skip] emergency contact '{emerg_name}' matches student's own name — ignored")
                        continue

                for perm in perm_records:
                    if _name_matches_perm(emerg_name, perm):
                        tier_desc = (f"emergency contact '{emerg_name}' "
                                     f"matched '{perm['first']} {perm['surname']}'")
                        confirmed_matches.append((perm['result'], tier_desc))
                        # Keep going — don't break. A student may have two parents
                        # both listed as emergency contacts who both filled the form.

            # ── Tier 2: Contact CSV SC1/SC2 — match perm first+last against
            #            the SC1/SC2 preferred+surname linked to this student
            if not confirmed_matches and using_contact:
                for perm in perm_records:
                    entries = parent_lookup.get(perm['surname'], [])
                    for entry in entries:
                        if entry['sid'] != sid:
                            continue
                        # Surname matches and is linked to this student.
                        # Also require first name to match (or be blank in contact CSV).
                        contact_first = entry['first']
                        first_pat = r'\b' + re.escape(perm['first']) + r'\b'
                        first_ok = (
                            not contact_first or
                            contact_first in ('nan', '') or
                            re.search(first_pat, contact_first) is not None
                        )
                        if first_ok:
                            tier_desc = f"contact CSV '{perm['first']} {perm['surname']}'"
                            confirmed_matches.append((perm['result'], tier_desc))
                            break

            # ── Resolve: among confirmed matches, No wins only over Yes.
            # An unrelated person sharing a surname is never in confirmed_matches
            # so their No cannot affect this student.
            if confirmed_matches:
                # If any confirmed parent said No, result is No
                if any(r == 'No' for r, _ in confirmed_matches):
                    final_result = 'No'
                else:
                    final_result = 'Yes'
                tiers = ', '.join(t for _, t in confirmed_matches)
                permissions[sid] = final_result
                print(f"  {final_result:3s} ← student {sid} via {tiers}")
            else:
                print(f"  --- ← student {sid} — no confirmed match (No Response)")

        yes_count = sum(1 for v in permissions.values() if v == 'Yes')
        no_count  = sum(1 for v in permissions.values() if v == 'No')
        nr_count  = sum(1 for v in permissions.values() if v == 'No Response')
        print(f"\nResults: Yes={yes_count}  No={no_count}  No Response={nr_count}")
        print(f"{'='*80}\n")
        return permissions

    except Exception as e:
        import traceback
        print(f"Error processing photo permissions CSV: {e}")
        print(traceback.format_exc())
        return {}

def _norm_student_id(v):
    """Normalise a student ID for comparison: strip spaces, drop a trailing '.0'
    (Excel numbers read back as floats) and ignore leading zeros."""
    s = str(v).strip()
    if s.lower() in ('', 'nan', 'none'):
        return ''
    if re.fullmatch(r'\d+\.0+', s):
        s = s.split('.')[0]
    return s.lstrip('0') or '0'


def read_no_photo_permission_xlsx(file_list):
    """
    Reads one or more 'students WITHOUT photo permission' Excel (.xlsx) exports
    and combines them into a single DataFrame (all values as text).
    Returns None if nothing could be read.
    """
    frames = []
    for f in file_list or []:
        try:
            if hasattr(f, 'seek'):
                f.seek(0)
            df = pd.read_excel(f, dtype=str, engine='openpyxl').fillna("")
            df.columns = [str(c).strip() for c in df.columns]
            frames.append(df)
        except Exception as e:
            print(f"[read_no_photo_permission_xlsx] Could not read '{getattr(f, 'name', '?')}': {e}")
            st.warning(f"Could not read '{getattr(f, 'name', 'file')}' as an Excel file: {e}")
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def apply_no_photo_permission_list(df_main, perm_map, noperm_df, default_result):
    """
    Applies a 'no photo permission' list (every student listed has NO permission)
    to the students in df_main (the student list / medical folder).

    Matching:
      1. Student ID (primary) — configurable column, default 'ID'.
      2. Fallback for rows whose ID isn't found: surname + first-or-preferred
         name, only when that combination identifies exactly ONE student in
         df_main.
    Listed students who are not in df_main are ignored.

    perm_map       – result from the CSV matcher ({} if no CSV was uploaded)
    default_result – value for students not touched by either source
                     ('Yes' when the list is the only source, because the list
                     contains everyone WITHOUT permission; otherwise the CSV
                     result is kept, falling back to 'No Response').
    Listed students always become 'No'.
    """
    cfg = CONFIG.get('photo_permission_xlsx_mappings', {})
    cols_lc = {str(c).strip().lower(): c for c in noperm_df.columns}

    def _col(key, default):
        return cols_lc.get(str(cfg.get(key, default)).strip().lower())

    id_col   = _col('student_id', 'ID')
    pref_col = _col('preferred_name', 'StudentPreferred')
    sur_col  = _col('surname', 'StudentSurname')

    result = {}
    id_lookup, name_lookup = {}, {}
    for _, row in df_main.iterrows():
        sid = str(row[COLS['student_id']])
        result[sid] = perm_map.get(sid, default_result)
        nid = _norm_student_id(sid)
        if nid:
            id_lookup[nid] = sid
        sur = _normalize_name_key(str(row[COLS['surname']])).lower()
        for fn in (row.get(COLS['first_name'], ''), row.get(COLS['preferred_name'], '')):
            fn = _normalize_name_key(str(fn)).lower()
            if sur and fn and fn != 'nan':
                name_lookup.setdefault((sur, fn), set()).add(sid)

    matched, by_name, listed = set(), 0, 0
    for _, row in noperm_df.iterrows():
        nid = _norm_student_id(row.get(id_col, '')) if id_col else ''
        pref = _normalize_name_key(str(row.get(pref_col, ''))).lower() if pref_col else ''
        sur = _normalize_name_key(str(row.get(sur_col, ''))).lower() if sur_col else ''
        if not nid and not (pref and sur):
            continue  # blank row
        listed += 1
        sid = id_lookup.get(nid) if nid else None
        if sid is None and pref and sur:
            candidates = name_lookup.get((sur, pref), set())
            if len(candidates) == 1:
                sid = next(iter(candidates))
                by_name += 1
        if sid is not None:
            matched.add(sid)

    for sid in matched:
        result[sid] = 'No'

    st.session_state.photo_noperm_stats = {
        'listed': listed, 'matched': len(matched), 'by_name': by_name,
    }
    print(f"[photo permissions] no-permission list: {listed} listed, "
          f"{len(matched)} matched to student list ({by_name} by name fallback)")
    return result


def has_photo_permission_data():
    """True if either a photo permission CSV or a no-permission Excel list is loaded."""
    return (st.session_state.get('photo_perm_csv') is not None or
            st.session_state.get('photo_noperm_df') is not None)


def compute_photo_permissions(df_main):
    """
    Builds the final { student_id: 'Yes'|'No'|'No Response' } map from whichever
    sources are loaded: the Paperly CSV(s), the no-permission Excel list, or both.
    The Excel list always forces 'No' for students it contains.
    """
    csv_data = st.session_state.get('photo_perm_csv')
    noperm   = st.session_state.get('photo_noperm_df')
    perm_map = match_photo_permissions(df_main, csv_data) if csv_data is not None else {}
    if noperm is not None:
        perm_map = apply_no_photo_permission_list(
            df_main, perm_map, noperm,
            default_result='Yes' if csv_data is None else 'No Response')
    return perm_map


def parse_learning_support(text):
    if not isinstance(text, str) or not text.strip(): return {} 

    # 0. GLOSSARY EXPANSION
    for acro, full in GLOSSARY.items():
        pattern = r'\b' + re.escape(acro) + r'\b'
        text = re.sub(pattern, full, text, flags=re.IGNORECASE)

    # 1. EXTRACT BADGES
    raw_codes = set(re.findall(r'(![A-Za-z]+)', text))
    clean_badges = []
    for code in raw_codes:
        label = LEARNING_CODES.get(code, code.replace("!", ""))
        clean_badges.append(label)
        text = text.replace(code, "")

    lines = text.split('\n')
    cleaned_lines = []
    
    line_killers = [
        "Synchronised from Paperly", "Last changed", "AEDT", "AEST", 
        "See ILP", "refer to Learning Profile", "found in the Student Plans", 
        "No Medical Conditions", "Educational assessment report on file",
        "An ILP will be added", "Effective August", "Effective 20"
    ]
    
    prefixes_to_strip = [
        "Learning Alert Diagnosis:", "Learning Alert:", "Diagnosis:", 
        "Adjustments:", "Accomodations:", "Accommodations:",
        "Considerations:", "Condition:"
    ]

    for line in lines:
        line_clean = line.strip()
        if not line_clean: continue
        
        if any(killer.lower() in line_clean.lower() for killer in line_killers):
            continue

        if line_clean.lower() == "learning alert":
            continue

        for prefix in prefixes_to_strip:
            if line_clean.lower().startswith(prefix.lower()):
                pattern = re.compile(re.escape(prefix), re.IGNORECASE)
                line_clean = pattern.sub("", line_clean, count=1).strip()

        line_clean = re.sub(r'[\s,]{2,}', ', ', line_clean)
        line_clean = line_clean.strip(" :,-")

        if line_clean:
            cleaned_lines.append(line_clean)

    seen = set()
    final_lines = []
    for x in cleaned_lines:
        if x not in seen:
            final_lines.append(x)
            seen.add(x)

    diagnosis_desc = "\n".join(final_lines)

    return {
        "diagnosis": diagnosis_desc if diagnosis_desc else "See Student Plans for details.",
        "accommodations": sorted(clean_badges)
    }

# ─────────────────────────────────────────────────────────────────────────────
# Y8 CAMP EXCEL PARSER
# ─────────────────────────────────────────────────────────────────────────────

_Y8_SKIP_SHEETS = {"not attending"}

# Sheets that contain the full leader overview data (case-insensitive match)
_Y8_LEADER_OVERVIEW_SHEETS = {"leader overview", "updated leader overview"}

_Y8_SURVEY_COLS = [
    # Activity columns — camp-specific
    "Sea Kayak",
    "Coasteer",
    "MTB Interest",
    "Snorkel",
    # General / shared columns
    "General Camping Skill",
    "Sleeping Outdoors/Bugs",
    "Swimming Confidence",
    "Bike Comfort",
    "Overnight Hike",
    "Reaction to Hardship",
    "Gear Independence",
    "Group Teamwork",
]

def parse_y8_camp_excel(uploaded_file):
    """
    Parse Updated_Leader_Overview.xlsx exported from the Y8 Camp Group Maker.

    The file exported by the Final Roster & Leader Builder page has a single
    sheet called "Updated Leader Overview" (sometimes "Leader Overview").
    Each real student row has:
        Student ID  |  Student  |  Class  |  Assigned Camp  |  <survey cols>

    Separator rows have '---' in the Student ID or Student columns and are
    skipped.  The 'Assigned Camp' column ('Freycinet' / 'Bay of Fires') is
    used directly — no need to track a running camp variable.

    Returns dict keyed by normalised Student ID string:
        { "12345": { "class": "Bracey", "camp": "Freycinet", <survey cols> } }
    """
    try:
        from openpyxl import Workbook  # noqa: F401 — registers openpyxl with pandas
    except ImportError:
        raise ValueError(
            "The openpyxl package is required to read .xlsx files. "
            "Install it by running:  pip install openpyxl  "
            "then restart the app."
        )

    uploaded_file.seek(0)
    xls = pd.ExcelFile(uploaded_file)
    sheet_names = xls.sheet_names

    result = {}

    # ── Strategy 1: Read the Leader Overview sheet directly ──────────────────
    # The Updated_Leader_Overview.xlsx from the "Final Roster & Leader Builder"
    # page has an "Updated Leader Overview" (or "Leader Overview") sheet with
    # an explicit "Assigned Camp" column and a "Class" column.
    leader_sheet = None
    for sname in sheet_names:
        if sname.strip().lower() in _Y8_LEADER_OVERVIEW_SHEETS:
            leader_sheet = sname
            break

    if leader_sheet:
        df_lo = pd.read_excel(xls, sheet_name=leader_sheet, dtype=str).fillna("")

        if 'Student ID' in df_lo.columns and 'Assigned Camp' in df_lo.columns:
            for _, row in df_lo.iterrows():
                st_id    = str(row.get('Student ID', '')).replace('.0', '').strip()
                stud_val = str(row.get('Student', '')).strip()
                camp_val = str(row.get('Assigned Camp', '')).strip()
                class_val = str(row.get('Class', '')).strip()

                # Skip separator / header rows
                if not st_id or st_id.lower() in ('nan', 'n/a', '---', 'student id', ''):
                    continue
                if st_id.startswith('---') or stud_val.startswith('---'):
                    continue
                # Skip rows without a real camp value
                if camp_val.startswith('---') or camp_val.lower() in ('nan', ''):
                    continue

                record = {"class": class_val, "camp": camp_val}
                for col_name in _Y8_SURVEY_COLS:
                    val = str(row.get(col_name, 'N/A')).strip()
                    # Treat '---' or blank as N/A
                    record[col_name] = val if val not in ('---', '', 'nan') else 'N/A'

                result[st_id] = record

            if result:
                return result

    # ── Strategy 2: Fallback — read class-named tabs ─────────────────────────
    # Supports the intermediate Camp_Allocations_Final.xlsx which has one tab
    # per class (Bracey, Knight, etc.) with a BAY OF FIRES separator row.
    for sheet in sheet_names:
        if sheet.strip().lower() in _Y8_SKIP_SHEETS:
            continue
        if sheet.strip().lower() in _Y8_LEADER_OVERVIEW_SHEETS:
            continue

        df_class = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")

        if 'Student ID' not in df_class.columns:
            continue

        current_camp = "Freycinet"

        for _, row in df_class.iterrows():
            stud_val = str(row.get('Student', '')).strip()
            st_id    = str(row.get('Student ID', '')).replace('.0', '').strip()

            # BAY OF FIRES separator row
            if 'BAY OF FIRES' in stud_val.upper() or 'BAY OF FIRES' in st_id.upper():
                current_camp = "Bay of Fires"
                continue

            # Skip blanks and separator rows
            if not st_id or st_id.lower() in ('nan', 'n/a', '---', 'student id', ''):
                continue
            if st_id.startswith('---'):
                continue

            record = {"class": sheet.strip(), "camp": current_camp}
            for col_name in _Y8_SURVEY_COLS:
                record[col_name] = str(row.get(col_name, 'N/A')).strip()

            result[st_id] = record

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Y9 CAMP — survey (1–10 ratings) + group allocation files
#
#  * Survey CSV : one row per student submission. Columns are found by KEYWORD in
#                 the (long) question text, so small wording changes don't break
#                 anything. Keywords can be overridden in config.yaml under
#                 `y9_camp_mappings`.
#  * Groups CSV : a "Week N: …" banner row, then a header row of <group name>, ID
#                 column pairs, then the student IDs under each ID column, then
#                 (after a blank row) optional notes and finally the leaders.
# ─────────────────────────────────────────────────────────────────────────────
_Y9_SORT_LABEL = "🏔️ Y9 Preloaded Camp Groups"

# Order here is just the order the keys exist; the booklet template decides the
# column order. Labels must match the names used in templates/profiles.html.
_Y9_SCORE_LABELS = ["White Water", "Challenge", "Camping", "Outdoors", "Swimming",
                    "Overnighter", "Hardship", "Gear", "Teamwork"]

_Y9_DEFAULT_MAPPINGS = {
    "timestamp_keyword": "timestamp",
    "email_keyword": "email",
    "name_keyword": "full name",
    "house_keyword": "which house",
    # booklet column  ->  text that must appear in the survey question (case-insensitive)
    "score_keywords": {
        "White Water": "white water",
        "Challenge":   "physical challenge would you prefer",
        "Camping":     "general camping skills",
        "Outdoors":    "sleeping outdoors",
        "Swimming":    "swimming in deep water",
        "Overnighter": "overnight hike",
        "Hardship":    "gets tiring",
        "Gear":        "organising your own gear",
        "Teamwork":    "work together",
    },
}


def _y9_cfg():
    """Default Y9 survey mappings, overridden by config.yaml -> y9_camp_mappings if present."""
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _Y9_DEFAULT_MAPPINGS.items()}
    user = CONFIG.get("y9_camp_mappings") or {}
    for k, v in user.items():
        if k == "score_keywords" and isinstance(v, dict):
            cfg["score_keywords"].update({str(a): str(b) for a, b in v.items() if b})
        elif v:
            cfg[k] = str(v)
    return cfg


def _y9_read_text(file_obj):
    """Read an uploaded CSV as text, tolerating Excel's UTF-8-with-BOM and Windows-1252 (en/em dashes)."""
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    raw = file_obj.read()
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _y9_assign_text_blocks(cols, blocks):
    """
    Under each week, text rows are grouped into blocks separated by blank rows.
    The LAST block is the leaders; any earlier block(s) are per-group notes
    (e.g. "KAYAK First" / "Walk First"). Values sit in each group's name column.
    """
    if not cols or not blocks:
        return
    leader_rows = blocks[-1]
    note_rows = [row for blk in blocks[:-1] for row in blk]
    for c in cols:
        nc = c["name_col"]
        c["group"]["leaders"] = [row[nc] for row in leader_rows if row[nc]]
        c["group"]["notes"]   = [row[nc] for row in note_rows if row[nc]]


def parse_y9_groups_csv(file_obj):
    """
    Parse the Y9 camp groups file.

    Returns {
      'groups': [ {key, week_label, week_detail, title, journey, ids, leaders, notes}, ... ]  (file order)
      'id_to_group': { normalised student id: group key },
      'warnings': [str]
    }
    """
    import csv, io
    text = _y9_read_text(file_obj)
    rows = [[(c or "").strip() for c in r] for r in csv.reader(io.StringIO(text))]
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]

    week_re = re.compile(r'^\s*(week\s*\d+)\s*[:\-–—]?\s*(.*)$', re.IGNORECASE)
    groups, warnings = [], []
    week_label, week_detail = "Groups", ""
    cols, blocks, cur_block = None, [], []

    for r in rows:
        m = week_re.match(r[0]) if r and r[0] else None
        if m and not any(r[1:]):
            # A new "Week N: …" banner — finish the previous week first.
            if cur_block:
                blocks.append(cur_block)
            _y9_assign_text_blocks(cols, blocks)
            week_label = re.sub(r"\s+", " ", m.group(1)).title()
            week_detail = m.group(2).strip()
            cols, blocks, cur_block = None, [], []
            continue

        if cols is None:
            # Looking for this week's header row: <group name>, ID, <group name>, ID, …
            id_cells = [i for i, c in enumerate(r) if c.lower() in ("id", "student id", "code")]
            if id_cells:
                cols = []
                for i in id_cells:
                    title = r[i - 1] if i > 0 else ""
                    if not title:
                        continue
                    title = re.sub(r"\s*[—–]\s*", " — ", title).strip()
                    journey = re.split(r"\s+—\s+|\s+-\s+", title)[0].strip()
                    g = {"key": f"{week_label} | {title}", "week_label": week_label,
                         "week_detail": week_detail, "title": title, "journey": journey,
                         "ids": [], "leaders": [], "notes": []}
                    groups.append(g)
                    cols.append({"name_col": i - 1, "id_col": i, "group": g})
            continue

        found_id = False
        for c in cols:
            v = r[c["id_col"]]
            if re.fullmatch(r"\d+(?:\.0+)?", v):
                c["group"]["ids"].append(v.split(".")[0])
                found_id = True
        if found_id:
            if cur_block:
                blocks.append(cur_block)
                cur_block = []
            continue
        if not any(r):
            if cur_block:
                blocks.append(cur_block)
                cur_block = []
            continue
        cur_block.append(r)

    if cur_block:
        blocks.append(cur_block)
    _y9_assign_text_blocks(cols, blocks)

    id_to_group = {}
    for g in groups:
        for gid in g["ids"]:
            nid = _norm_student_id(gid)
            if nid in id_to_group and id_to_group[nid] != g["key"]:
                warnings.append(f"Student ID {gid} is listed in more than one group "
                                f"({id_to_group[nid]} and {g['key']}) — the first one is used.")
            else:
                id_to_group[nid] = g["key"]

    return {"groups": groups, "id_to_group": id_to_group, "warnings": warnings}


def _y9_score(v):
    """'7' / '7.0' -> '7'; anything blank or outside 1–10 -> 'N/A'."""
    try:
        n = int(round(float(str(v).strip())))
    except (ValueError, TypeError):
        return "N/A"
    return str(n) if 1 <= n <= 10 else "N/A"


def parse_y9_survey_csv(file_obj):
    """
    Parse the Y9 camp survey export.
    Returns (records, info). Each record:
        {'name','email','house','timestamp','scores':{label: '1'..'10'|'N/A'}, '_index'}
    info = {'missing': [score labels whose question could not be found], 'rows': int}
    """
    import io
    cfg = _y9_cfg()
    df = pd.read_csv(io.StringIO(_y9_read_text(file_obj)), dtype=str, keep_default_na=False)
    heads = {c: re.sub(r"\s+", " ", str(c)).strip().lower() for c in df.columns}
    used = set()

    def _find(keyword):
        kw = str(keyword).strip().lower()
        if not kw:
            return None
        for c, h in heads.items():
            if c not in used and kw in h:
                used.add(c)
                return c
        return None

    ts_col    = _find(cfg["timestamp_keyword"])
    email_col = _find(cfg["email_keyword"])
    name_col  = _find(cfg["name_keyword"])
    house_col = _find(cfg["house_keyword"])
    score_cols = {lab: _find(cfg["score_keywords"].get(lab, "")) for lab in _Y9_SCORE_LABELS}

    if ts_col:
        ts = pd.to_datetime(df[ts_col], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        if ts.isna().any():
            ts = ts.fillna(pd.to_datetime(df[ts_col], dayfirst=True, errors="coerce"))
    else:
        ts = pd.Series([pd.NaT] * len(df), index=df.index)

    records = []
    for idx, row in df.iterrows():
        scores = {lab: (_y9_score(row[col]) if col else "N/A") for lab, col in score_cols.items()}
        if all(v == "N/A" for v in scores.values()):
            continue
        records.append({
            "name":      str(row[name_col]).strip()  if name_col  else "",
            "email":     str(row[email_col]).strip() if email_col else "",
            "house":     str(row[house_col]).strip() if house_col else "",
            "timestamp": ts.loc[idx],
            "scores":    scores,
            "_index":    int(idx),
        })

    missing = [lab for lab, col in score_cols.items() if col is None]
    return records, {"missing": missing, "rows": len(df)}


def _y9_norm_name(s):
    """Lower-case, accent-free, punctuation-free name so 'Tran-Lau' == 'tran lau' and "O'Brien" == 'obrien'."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = s.replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _y9_ts(rec):
    ts = rec.get("timestamp")
    return ts if ts is not None and pd.notna(ts) else pd.Timestamp.min


def _y9_student_index(df):
    id_col = COLS["student_id"]
    fn_col = COLS["first_name"]
    pn_col = COLS.get("preferred_name", "Preferred name")
    sn_col = COLS["surname"]
    hs_col = COLS.get("house", "House")

    email_col = None
    for cand in ["Email", "email", "Email address", "Email Address",
                 "Student email", "Student Email", "EmailAddress"]:
        if cand in df.columns:
            email_col = cand
            break
    if email_col is None:
        email_col = next((c for c in df.columns if "email" in str(c).lower()), None)

    students = []
    for _, r in df.iterrows():
        sid = str(r.get(id_col, "")).strip()
        first = _y9_norm_name(r.get(fn_col, ""))
        pref = _y9_norm_name(r.get(pn_col, "")) or first
        sur = _y9_norm_name(r.get(sn_col, ""))
        if not sid or not sur:
            continue
        names = set()
        for f in {first, pref}:
            if f:
                names.add(f"{f} {sur}")
                names.add(f"{sur} {f}")
        students.append({
            "sid": sid,
            "house": _y9_norm_name(r.get(hs_col, "")),
            "email": str(r.get(email_col, "")).strip().lower() if email_col else "",
            "names": names,
            "tokens": set(first.split()) | set(pref.split()) | set(sur.split()),
            "sur_tokens": set(sur.split()),
            "first_toks": set(first.split()[:1]) | set(pref.split()[:1]),
            "label": f"{str(r.get(fn_col, '')).strip()} {str(r.get(sn_col, '')).strip()} ({sid})",
        })
    return students


def _y9_pick(cands, house):
    """One candidate -> that one. Several -> narrow by House if that leaves exactly one. Otherwise None."""
    if len(cands) == 1:
        return cands[0]
    if house:
        narrowed = [c for c in cands if c["house"] == house]
        if len(narrowed) == 1:
            return narrowed[0]
    return None


def _y9_match_one(rec, students, by_email, by_name):
    """
    Returns (student or None, suggestion or None).
    Only unambiguous matches are accepted automatically; anything doubtful comes
    back as a *suggestion* for the manual-matching list instead.
    """
    house = _y9_norm_name(rec.get("house", ""))

    # 1) Email — most reliable
    em = (rec.get("email") or "").strip().lower()
    if em and len(by_email.get(em, [])) == 1:
        return by_email[em][0], None

    nm = _y9_norm_name(rec.get("name", ""))
    if not nm:
        return None, None

    # 2) Exact full name (first OR preferred name + surname, either order)
    cands = by_name.get(nm, [])
    if cands:
        hit = _y9_pick(cands, house)
        return (hit, None) if hit else (None, cands[0])

    # 3) Name contains / is contained in the student's name tokens (middle names etc.)
    toks = set(nm.split())
    if len(toks) >= 2:
        cands = [s for s in students
                 if (toks & s["sur_tokens"])
                 and (toks <= s["tokens"] or (s["sur_tokens"] <= toks and (s["first_toks"] & toks)))]
        if cands:
            hit = _y9_pick(cands, house)
            return (hit, None) if hit else (None, cands[0])

    # 4) Typos — only auto-accept a very close, unambiguous hit
    close = difflib.get_close_matches(nm, list(by_name.keys()), n=5, cutoff=0.75)
    if not close:
        return None, None
    best = close[0]
    best_students = by_name[best]
    ratio = difflib.SequenceMatcher(None, nm, best).ratio()
    best_sids = {s["sid"] for s in best_students}
    rivals = {s["sid"] for v in close[1:]
              if difflib.SequenceMatcher(None, nm, v).ratio() >= ratio - 0.05
              for s in by_name[v]} - best_sids
    if ratio >= 0.92 and len(best_students) == 1 and not rivals:
        return best_students[0], None
    return None, best_students[0]


def match_y9_survey(records, df_students):
    """
    Match survey records to students in the student list (email → name → fuzzy).
    If a student submitted more than once, the NEWEST submission wins.

    Returns (matched {student_id: record}, unmatched [record + '_suggest'], stats)
    """
    students = _y9_student_index(df_students)
    by_email, by_name = {}, {}
    for s in students:
        if s["email"]:
            by_email.setdefault(s["email"], []).append(s)
        for n in s["names"]:
            by_name.setdefault(n, []).append(s)

    newest, pending, n_dupes = {}, [], 0
    for rec in records:
        stu, sug = _y9_match_one(rec, students, by_email, by_name)
        if stu is None:
            r2 = dict(rec)
            r2["_suggest"] = {"sid": sug["sid"], "label": sug["label"]} if sug else None
            pending.append(r2)
            continue
        cur = newest.get(stu["sid"])
        if cur is None:
            newest[stu["sid"]] = rec
        else:
            n_dupes += 1
            if _y9_ts(rec) >= _y9_ts(cur):
                newest[stu["sid"]] = rec

    # The same unmatched person may also have submitted twice — keep their newest.
    keep = {}
    for rec in pending:
        key = (rec.get("email") or "").lower() or _y9_norm_name(rec.get("name", "")) or f"row{rec['_index']}"
        cur = keep.get(key)
        if cur is None:
            keep[key] = rec
        else:
            n_dupes += 1
            if _y9_ts(rec) >= _y9_ts(cur):
                keep[key] = rec
    unmatched = sorted(keep.values(), key=lambda r: r["_index"])

    stats = {"responses": len(records), "matched": len(newest),
             "unmatched": len(unmatched), "duplicates": n_dupes}
    print(f"[Y9 survey] {stats['responses']} responses → {stats['matched']} matched, "
          f"{stats['unmatched']} need manual matching, {stats['duplicates']} older duplicate(s) ignored")
    return newest, unmatched, stats


def build_y9_final_scores():
    """{ normalised student id: scores dict } from automatic + manual survey matches."""
    out = {}
    for sid, rec in (st.session_state.get("y9_survey_matched") or {}).items():
        out[_norm_student_id(sid)] = rec["scores"]
    pending = {u["_index"]: u for u in (st.session_state.get("y9_survey_unmatched") or [])}
    for idx, sid in (st.session_state.get("y9_survey_manual") or {}).items():
        rec = pending.get(idx)
        if rec:
            out[_norm_student_id(sid)] = rec["scores"]
    return out


# ---------------------------------------------------------------------------
# Ligature / unknown-glyph map.
# The FB-block entries are standard Unicode ligatures.
# The LIGATURE_MAP at module level is checked first; then any char
# in the PUA range (E000-F8FF) that is NOT in the map is treated as
# "tt" as a fallback (the most common unmapped school-photo glyph).
# ---------------------------------------------------------------------------
LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

# Accumulates any PUA chars we actually encounter, for the debug log.
_SEEN_PUA_CHARS = set()


def _normalize_name_key(s):
    """
    Strip spaces and any dash/hyphen-like or apostrophe-like character from
    a name, regardless of which exact Unicode codepoint was used. PDF
    exports sometimes render a hyphenated surname using a non-breaking
    hyphen (U+2011) or similar instead of a plain ASCII "-", which looks
    identical on screen but would otherwise silently fail a `.replace("-", "")`
    based exact-match comparison, even though the name displays correctly.
    """
    if not isinstance(s, str):
        return s
    s = re.sub(r'[\s\u00A0]', '', s)
    s = re.sub(r'[-\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', '', s)
    s = re.sub(r"['\u2018\u2019\u02BC\u0060]", '', s)
    return s


def _smart_join(parts):
    """
    Join adjacent PDF word fragments into a readable string.
    Font kerning around a hyphen glyph occasionally causes pdfplumber to
    split a hyphenated name into two separate word tokens on the same line
    (e.g. "Blackway-" and "Cole"). A plain " ".join() then reads
    "Blackway- Cole". This joins normally, but skips the space when the
    previous fragment already ends in a hyphen.
    """
    out = ""
    for part in parts:
        if not out:
            out = part
        elif out.endswith("-"):
            out += part
        else:
            out += " " + part
    return out


def clean_ligatures(text):
    """
    Centralised ligature / glyph cleanup.
    1. Known ligatures (FB block) are replaced by their expansions.
    2. ANY Private-Use-Area character (U+E000–U+F8FF) not already in
       LIGATURE_MAP is assumed to be 'tt' (by far the most common
       unmapped glyph in school-photo PDFs) and replaced accordingly.
       The char is also logged to _SEEN_PUA_CHARS for the debug dump.
    3. Zero-width / invisible formatting chars are stripped.
    4. Any run of 3+ identical letters is collapsed to exactly 2.
       This handles pdfplumber emitting phantom duplicate chars after
       a ligature glyph (e.g. [PUA]+"tt" -> "tttt" collapses to "tt").
       No English surname has 3+ of the same letter in a row.
    """
    out = []
    for ch in text:
        cp = ord(ch)
        # Known ligature?
        if ch in LIGATURE_MAP:
            out.append(LIGATURE_MAP[ch])
        # PUA fallback — treat as 'tt'
        elif 0xE000 <= cp <= 0xF8FF:
            _SEEN_PUA_CHARS.add(ch)
            out.append("tt")
        # Zero-width / invisible — drop
        elif cp in (0x200B, 0x200C, 0x200D, 0xFEFF):
            continue
        else:
            out.append(ch)
    # Collapse runs of 3+ identical letters -> 2
    return re.sub(r'(.)\1{2,}', r'\1\1', "".join(out))


def debug_dump_pua_chars():
    """Call after scanning to see every PUA char that was hit."""
    if _SEEN_PUA_CHARS:
        print("=== PUA chars encountered (all mapped to 'tt') ===")
        for ch in sorted(_SEEN_PUA_CHARS, key=ord):
            print(f"  U+{ord(ch):04X}  repr={repr(ch)}")
    else:
        print("=== No PUA chars encountered ===")


# ---------------------------------------------------------------------------
# Proactive name pattern risk-scan.
# Runs against the roster's raw text (surname/first/preferred name) rather
# than anything extracted from a PDF, looking for the SAME classes of
# character that have historically caused problems here — the ligature
# letter-pairs in LIGATURE_MAP (plus the "tt"/"ti" pair, since that's what
# an unrecognised ligature glyph gets guessed as), non-ASCII characters,
# and hyphen/apostrophe variants (already special-cased in
# _normalize_name_key because PDF exports sometimes use a lookalike
# Unicode character instead of a plain "-" or "'").
# The point isn't that these patterns ARE bugs — most resolve fine — it's
# an early warning so a name like "Matti" or "O'Brien-Smith" can be
# checked deliberately instead of only being noticed after a photo goes
# missing.
# ---------------------------------------------------------------------------
_RISK_LIGATURE_PATTERNS = ["ffi", "ffl", "ff", "fi", "fl", "st", "tti", "tt", "ti"]


def _scan_name_pattern_risks(df, mapping):
    """
    Returns a list of dicts: {code, field, category, detail}
    - code: the anonymised code for the value that triggered the flag
    - field: "Surname" / "First name" / "Preferred name"
    - category: short risk category label
    - detail: the specific matched fragment/character (never the full name)
    """
    findings = []
    if df is None or getattr(df, "empty", True) or not mapping:
        return findings

    field_cols = [
        ("Surname", COLS.get("surname")),
        ("First name", COLS.get("first_name")),
        ("Preferred name", COLS.get("preferred_name")),
    ]

    seen = set()  # (code, category, detail) — dedupe repeats across rows
    for field_label, col in field_cols:
        if not col or col not in df.columns:
            continue
        for raw_val in df[col].dropna().astype(str):
            val = raw_val.strip()
            if not val:
                continue
            code = mapping.get(val.lower())
            if not code:
                continue
            low = val.lower()

            # Classic ligature-prone sequences
            already_flagged_ligature = False
            for pat in _RISK_LIGATURE_PATTERNS:
                if pat in low and not already_flagged_ligature:
                    key = (code, "Ligature-prone sequence", pat)
                    if key not in seen:
                        seen.add(key)
                        findings.append({
                            "code": code, "field": field_label,
                            "category": "Ligature-prone sequence",
                            "detail": f"contains \"{pat}\"",
                        })
                    already_flagged_ligature = True  # one flag per value is enough

            # Non-ASCII characters (accents, macrons, etc.)
            for ch in val:
                if ord(ch) > 127:
                    key = (code, "Non-ASCII character", ch)
                    if key not in seen:
                        seen.add(key)
                        findings.append({
                            "code": code, "field": field_label,
                            "category": "Non-ASCII character",
                            "detail": f"contains \"{ch}\" (U+{ord(ch):04X})",
                        })

            # Hyphen variants
            if re.search(r'[-\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', val):
                key = (code, "Hyphen", "-")
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "code": code, "field": field_label,
                        "category": "Hyphen",
                        "detail": "contains a hyphen/dash",
                    })

            # Apostrophe variants
            if re.search(r"['\u2018\u2019\u02BC\u0060]", val):
                key = (code, "Apostrophe", "'")
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "code": code, "field": field_label,
                        "category": "Apostrophe",
                        "detail": "contains an apostrophe",
                    })

    return findings


def extract_photos_geometric(photo_pdf_path, df):
    results = {}
    unmatched_data = []
    collisions = []
    match_method_counts = {}

    if not photo_pdf_path:
        return results, unmatched_data, collisions

    print(f"\n--- Starting Geometric Extraction: {os.path.basename(photo_pdf_path)} ---")

    # ------------------------------------------------------------------
    # 1. Prepare Student Data
    # ------------------------------------------------------------------
    student_map = {}
    
    # Debug counter
    total_students = 0

    for _, row in df.iterrows():
        s_last  = str(row[COLS['surname']]).strip().lower()
        s_first = str(row[COLS['first_name']]).strip().lower()
        s_id    = str(row[COLS['student_id']])
        s_roll  = str(row[COLS['rollgroup']]).strip().lower()

        # Clean the key the same way we'll clean PDF text:
        clean_key = clean_ligatures(_normalize_name_key(s_last))

        if clean_key not in student_map:
            student_map[clean_key] = []

        student_map[clean_key].append({
            "id":        s_id,
            "roll":      s_roll,
            "first":     s_first,
            "orig_last": s_last,
        })
        total_students += 1

    print(f"[DEBUG] Loaded {total_students} students ({len(student_map)} unique surnames).")

    # Collision-risk census — print this BEFORE anything can go wrong, so
    # a scan always tells you up front which surname groups have 2+
    # students and are therefore the ones disambiguation logic actually
    # has to work for. If a photo ever goes to the wrong student, it will
    # always be one of the surnames listed here.
    _dupe_groups = {k: v for k, v in student_map.items() if len(v) > 1}
    if _dupe_groups:
        print(f"[DEBUG] {len(_dupe_groups)} surname group(s) have 2+ students (disambiguation required):")
        for key, group in _dupe_groups.items():
            ids = ", ".join(g["id"] for g in group)
            print(f"  [DEBUG]   Surname key '{key}': {len(group)} students (IDs: {ids})")
    else:
        print("[DEBUG] No duplicate surname groups this roster — every surname is unique.")

    # ------------------------------------------------------------------
    # 2. Constants
    # ------------------------------------------------------------------
    MAX_V_GAP        = 35    
    LOOKAHEAD_FENCE = 40    
    SAME_LINE_TOL    = 8     
    COL_PAD          = 30

    # ------------------------------------------------------------------
    # 2b. Helpers (closures over the per-page state set inside the loop
    #     below — `words`, `page`, `images`, `claimed_images` — resolved
    #     at call time, so it's safe to define these before that loop).
    # ------------------------------------------------------------------
    def _spatial_chain(start_idx, length, exclude=()):
        """
        Build a candidate phrase of `length` words anchored at
        words[start_idx], choosing each subsequent word by ON-PAGE
        POSITION rather than by its position in the `words` list.

        pdfplumber's default word ordering clusters words into "lines" by
        top-position across the WHOLE page width, then sorts left-to-right
        within each line. In a multi-column grid of photo labels, that
        means the word immediately AFTER "Blackway-" in `words` is often a
        neighbouring label's word (same row, next column over) rather than
        "Cole" wrapping onto the line below inside the SAME label — so the
        plain words[i:i+length] slice used elsewhere silently grabs the
        wrong words and the surname never matches. This walks the whole
        word list by geometry instead, to find the real continuation
        word(s) for a surname that wraps across two lines.

        `exclude` is a set of word-indices already consumed by an earlier
        successful match on this page (e.g. another student's surname) —
        they're skipped so one label's words can't be borrowed into
        another label's phrase.

        Returns a list of word-indices (possibly non-contiguous in
        `words`), in reading order, or None if no plausible chain of
        `length` words can be formed.
        """
        chain_idx = [start_idx]
        for _ in range(length - 1):
            last = words[chain_idx[-1]]
            last_cx = (last['x0'] + last['x1']) / 2
            best_idx, best_score = None, None
            for idx, w in enumerate(words):
                if idx in chain_idx or idx in exclude:
                    continue
                same_line = (abs(w['top'] - last['top']) <= SAME_LINE_TOL
                             and -2 <= (w['x0'] - last['x1']) <= 15)
                # Next line down, still inside the same narrow column —
                # a wrapped continuation of a multi-line surname.
                w_cx = (w['x0'] + w['x1']) / 2
                wrapped = (0 < (w['top'] - last['top']) <= 22
                           and abs(w_cx - last_cx) <= 70)
                if not (same_line or wrapped):
                    continue
                # Same-line candidates are scored by horizontal gap (how
                # close it sits to the right of the previous word).
                # Wrapped (next-line) candidates are scored primarily by
                # vertical gap, then by how well their x-centre lines up
                # with the previous word's — NOT by x0 vs the previous
                # word's x1, which are on different lines and not
                # meaningfully adjacent. Using the same "gap to x1" score
                # for both cases wrongly favoured a same-line neighbour's
                # first-name word over the correct next-line surname
                # continuation.
                if same_line:
                    score = abs(w['x0'] - last['x1'])
                else:
                    score = (w['top'] - last['top']) * 10 + abs(w_cx - last_cx)
                if best_score is None or score < best_score:
                    best_score, best_idx = score, idx
            if best_idx is None:
                return None
            chain_idx.append(best_idx)
        return chain_idx

    def _try_process_phrase(phrase_objs):
        """
        Given a candidate list of word-objects that might form a surname
        phrase, build the lookup key, resolve ambiguity, and (if a photo
        is found) claim + save the crop. Returns True if a student was
        successfully matched and processed, False otherwise (caller
        should try a different candidate / shorter length).
        """
        raw_text = "".join(w['text'] for w in phrase_objs).lower()
        text = clean_ligatures(raw_text)
        text = text.replace(",", "").replace(":", "").replace(".", "")
        text = _normalize_name_key(text)

        if text not in student_map:
            # Ligature-glyph fallback: clean_ligatures() has to guess when
            # it hits an unmapped PUA glyph, and its guess ("tt") is
            # sometimes wrong for glyphs that are actually "ti" (e.g.
            # "Jotic" -> "Jottc"). Try both re-substitutions against the
            # real roster instead of giving up on the first miss.
            alt_match = None
            for pat, repl in ((r'ti', 'tt'), (r'tt', 'ti')):
                alt = re.sub(pat, repl, text)
                if alt != text and alt in student_map:
                    alt_match = alt
                    break
            if alt_match is None:
                return False
            text = alt_match

        # --- FOUND A SURNAME MATCH ---
        candidates = student_map[text]

        # Spatial bounds
        surname_bottom = max(w['bottom'] for w in phrase_objs)
        phrase_x0      = min(w['x0']      for w in phrase_objs)
        phrase_x1      = max(w['x1']      for w in phrase_objs)
        col_x0 = phrase_x0 - COL_PAD
        col_x1 = phrase_x1 + COL_PAD

        # SPATIALLY-FILTERED LOOKAHEAD.
        # Kept as individual (word, cleaned_text) pairs, not just a single
        # flattened string — see disambiguation below for why.
        nearby_words = []
        for w_any in words:
            if w_any['top'] < surname_bottom - 2: continue
            if w_any['top'] > surname_bottom + LOOKAHEAD_FENCE: continue
            if w_any['x1'] < col_x0 or w_any['x0'] > col_x1: continue
            nearby_words.append((w_any, clean_ligatures(w_any['text'].lower())))

        nearby_text = _smart_join(w_text for _, w_text in nearby_words)
        phrase_cx = (phrase_x0 + phrase_x1) / 2

        # PICK THE STUDENT
        matched_student_id = None
        disambiguation_method = "Single Match"

        if len(candidates) == 1:
            matched_student_id = candidates[0]['id']
        else:
            # Two (or more) students sharing this surname are usually
            # sorted right next to each other in the label grid, so the
            # lookahead zone for ONE student's surname very often also
            # catches the NEXT student's first name spilling in from the
            # neighbouring label. A plain "is this substring anywhere in
            # the lookahead text" check can't tell those apart, and just
            # always picks whichever candidate happens to come first in
            # the roster's row order — silently giving one sibling/
            # namesake's photo to the other, every time, regardless of
            # which label is actually being looked at. Instead, find the
            # geometrically CLOSEST matching word to this specific
            # surname occurrence and let that decide.
            disambiguation_method = "First Name"
            best_cand, best_dist, tied = None, None, False
            best_cand_fuzzy, best_dist_fuzzy, tied_fuzzy = None, None, False
            for cand in candidates:
                if not cand['first']:
                    continue
                for w_any, w_text in nearby_words:
                    w_clean = w_text.strip(" ,.:-")
                    if w_clean != cand['first'] and cand['first'] not in w_text:
                        continue
                    w_cx = (w_any['x0'] + w_any['x1']) / 2
                    dist = (w_any['top'] - surname_bottom) * 10 + abs(w_cx - phrase_cx)
                    if w_clean == cand['first']:
                        # Exact whole-word match — most reliable signal.
                        if best_dist is None or dist < best_dist - 0.01:
                            best_dist, best_cand, tied = dist, cand, False
                        elif abs(dist - best_dist) <= 0.01 and cand is not best_cand:
                            # A second candidate matched an equally-close word
                            # — a genuine tie, not just noise. Guessing here
                            # would silently give one student's photo to the
                            # other, so this occurrence is left unmatched
                            # instead (it'll show up for manual review)
                            # rather than picking arbitrarily.
                            tied = True
                    else:
                        # Substring-only match — kept as a fallback for
                        # OCR/ligature quirks, but NOT trusted over an
                        # exact match. A substring check alone can match
                        # the wrong sibling when one candidate's first
                        # name is a prefix of the other's (e.g. "Eli"
                        # inside "Elijah", "Jack" inside "Jackson"),
                        # which used to silently swap same-surname pairs'
                        # photos whenever their names happened to nest
                        # like that.
                        if best_dist_fuzzy is None or dist < best_dist_fuzzy - 0.01:
                            best_dist_fuzzy, best_cand_fuzzy, tied_fuzzy = dist, cand, False
                        elif abs(dist - best_dist_fuzzy) <= 0.01 and cand is not best_cand_fuzzy:
                            tied_fuzzy = True
            if best_cand and not tied:
                matched_student_id = best_cand['id']
            elif best_cand_fuzzy and not tied_fuzzy:
                matched_student_id = best_cand_fuzzy['id']

            if matched_student_id is None:
                disambiguation_method = "Roll Group"
                best_cand, best_dist, tied = None, None, False
                best_cand_fuzzy, best_dist_fuzzy, tied_fuzzy = None, None, False
                for cand in candidates:
                    if not cand['roll']:
                        continue
                    for w_any, w_text in nearby_words:
                        w_clean = w_text.strip(" ,.:-")
                        if w_clean != cand['roll'] and cand['roll'] not in w_text:
                            continue
                        w_cx = (w_any['x0'] + w_any['x1']) / 2
                        dist = (w_any['top'] - surname_bottom) * 10 + abs(w_cx - phrase_cx)
                        if w_clean == cand['roll']:
                            if best_dist is None or dist < best_dist - 0.01:
                                best_dist, best_cand, tied = dist, cand, False
                            elif abs(dist - best_dist) <= 0.01 and cand is not best_cand:
                                # Roll group / homeroom is often shared by
                                # more than one student with the same
                                # surname (e.g. siblings or namesakes in the
                                # same class), so this tie is expected
                                # sometimes, not a bug — there's no more
                                # information in the PDF to break it safely,
                                # so this occurrence goes to manual review
                                # instead of guessing which student it is.
                                tied = True
                        else:
                            if best_dist_fuzzy is None or dist < best_dist_fuzzy - 0.01:
                                best_dist_fuzzy, best_cand_fuzzy, tied_fuzzy = dist, cand, False
                            elif abs(dist - best_dist_fuzzy) <= 0.01 and cand is not best_cand_fuzzy:
                                tied_fuzzy = True
                if best_cand and not tied:
                    matched_student_id = best_cand['id']
                elif best_cand_fuzzy and not tied_fuzzy:
                    matched_student_id = best_cand_fuzzy['id']

        if matched_student_id is None:
            print(f"  [DEBUG] AMBIGUOUS: Found surname '{text}' but could not match First/Roll in nearby text: '{nearby_text}'")
            match_method_counts["AMBIGUOUS (unmatched)"] = match_method_counts.get("AMBIGUOUS (unmatched)", 0) + 1
            return False

        print(f"  [DEBUG] MATCHED Name: '{text}' -> ID: {matched_student_id} (via {disambiguation_method})")
        match_method_counts[disambiguation_method] = match_method_counts.get(disambiguation_method, 0) + 1

        # GEOMETRY: Find photo
        phrase_top = min(w['top'] for w in phrase_objs)
        phrase_cx  = (phrase_x0 + phrase_x1) / 2

        best_img_idx = None
        best_img     = None
        min_gap      = 9999

        for img_idx, img in enumerate(images):
            if img_idx in claimed_images: continue # Skip already taken

            img_bot = img['bottom']
            if img_bot >= phrase_top: continue # Not above

            gap = phrase_top - img_bot
            if gap > MAX_V_GAP:
                if gap < MAX_V_GAP + 20:
                    print(f"    [Img {img_idx}] REJECTED: Too high (Gap {gap:.1f} > {MAX_V_GAP})")
                continue

            img_cx = (img['x0'] + img['x1']) / 2
            h_dist = abs(img_cx - phrase_cx)
            allowed_h_dist = (phrase_x1 - phrase_x0) / 2 + 40

            if h_dist > allowed_h_dist:
                print(f"    [Img {img_idx}] REJECTED: Off-center (Dist {h_dist:.1f} > {allowed_h_dist:.1f})")
                continue

            if gap < min_gap:
                min_gap      = gap
                best_img     = img
                best_img_idx = img_idx

        if best_img:
            print(f"    [Img {best_img_idx}] CLAIMED: Gap={min_gap:.1f}")
            try:
                claimed_images.add(best_img_idx)
                bbox = (best_img['x0'], best_img['top'],
                        best_img['x1'], best_img['bottom'])
                crop   = page.within_bbox(bbox)
                im_obj = crop.to_image(resolution=200).original
                save_path = os.path.join(
                    TEMP_DIR, f"{matched_student_id}.jpg"
                )
                im_obj.save(save_path)
                if matched_student_id in results:
                    # This ID already has a photo from earlier in this same
                    # scan — writing again would silently overwrite it and
                    # is very likely the "duplicate surname" failure mode:
                    # two different labels in the PDF both resolved to the
                    # same student. Surface it instead of losing it quietly.
                    print(f"    [COLLISION] Student ID {matched_student_id} already has a photo "
                          f"assigned this scan — about to be overwritten. Likely a duplicate-surname mismatch.")
                    collisions.append({
                        "id": matched_student_id,
                        "previous_path": results[matched_student_id],
                        "new_path": save_path,
                        "matched_via": disambiguation_method,
                    })
                results[matched_student_id] = save_path
            except Exception as e:
                print(f"    [ERROR] Saving image: {e}")
        else:
            print(f"    [WARNING] No valid image found above '{text}' (Max Gap: {MAX_V_GAP})")

        return True

    # ------------------------------------------------------------------
    # 3. Walk the PDF
    # ------------------------------------------------------------------
    with pdfplumber.open(photo_pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            print(f"\n[DEBUG] Processing Page {page_num + 1}...")
            words  = page.extract_words()
            images = page.images
            claimed_images = set()

            print(f"[DEBUG] Found {len(words)} words and {len(images)} images on page.")

            # ----------------------------------------------------------
            # A. NAME MATCHING
            # ----------------------------------------------------------
            i = 0
            # Indices already used in a successful match (contiguous or
            # spatially-chained). Skipped as future phrase-starts so a
            # word can't be claimed by two different students, but — 
            # unlike jumping `i` forward past them — words that were
            # never actually consumed (e.g. a neighbouring label's word
            # that a chain search merely looked at and rejected) stay
            # available to be matched on their own.
            consumed = set()
            while i < len(words):
                if i in consumed:
                    i += 1
                    continue

                words_skipped = 1

                for length in [5, 4, 3, 2, 1]:
                    if i + length > len(words):
                        continue

                    phrase_objs = words[i : i + length]

                    # SAME-LINE GUARD — with wrapped-surname relaxation.
                    # Multi-word surnames (e.g. "Jarretto Handerstaay") and
                    # hyphenated names with a space ("Duskett- McDann") can
                    # wrap onto the next line in a narrow photo-label column.
                    # In those cases the words' `top` values differ by one
                    # full line height (~12 px), exceeding SAME_LINE_TOL=8
                    # and causing a missed match.
                    # For multi-word phrases we allow the relaxed tolerance
                    # when the words stay inside the same narrow column
                    # (x-centre spread < 70 px) and appear in reading order.
                    tops = [w['top'] for w in phrase_objs]
                    vertical_spread = max(tops) - min(tops)
                    guard_ok = True
                    if vertical_spread > SAME_LINE_TOL:
                        if length > 1:
                            # Are all words horizontally within the same narrow column?
                            x_centres = [(w['x0'] + w['x1']) / 2 for w in phrase_objs]
                            same_col   = (max(x_centres) - min(x_centres)) < 70
                            # Also allow when the first word ends in '-' (hyphenated wrap)
                            is_hyphen_wrap = phrase_objs[0]['text'].rstrip().endswith('-')
                            # Words must appear in descending / non-reversed order (top-to-bottom)
                            in_order = all(
                                phrase_objs[j]['top'] <= phrase_objs[j+1]['top'] + 5
                                for j in range(len(phrase_objs) - 1)
                            )
                            guard_ok = (same_col or is_hyphen_wrap) and in_order and vertical_spread <= 22
                        else:
                            guard_ok = False

                    if any((i + k) in consumed for k in range(length)):
                        # A word later in this window was already claimed
                        # by an earlier spatially-chained match — don't
                        # reuse it in a contiguous phrase.
                        pass
                    elif guard_ok and _try_process_phrase(phrase_objs):
                        words_skipped = length
                        consumed.update(range(i, i + length))
                        break

                    # SPATIAL WRAP FALLBACK.
                    # The slice above (words[i:i+length]) assumes the word
                    # that continues a wrapped surname sits right after it
                    # in `words`. That's often false in a multi-column photo
                    # grid: pdfplumber orders words into page-wide "lines"
                    # by top-position, so the next word in the list is
                    # frequently a NEIGHBOURING label's word on the same
                    # row, not this label's second line ("Blackway-" is
                    # followed in `words` by e.g. the next column's surname,
                    # not "Cole"). That silently poisons the phrase's key
                    # and the match is lost. Search by geometry instead of
                    # list order to find the real continuation word(s).
                    #
                    # Only the matched words are marked `consumed` — `i`
                    # itself only ever advances by 1 here (not by however
                    # far away the furthest chained word was), so an
                    # unrelated word that merely sat between them in list
                    # order (e.g. a neighbouring column's surname) is left
                    # untouched and still gets its own turn as a phrase
                    # start.
                    if length > 1:
                        idx_chain = _spatial_chain(i, length, exclude=consumed)
                        if idx_chain:
                            chain_objs = [words[idx] for idx in idx_chain]
                            if chain_objs != phrase_objs and _try_process_phrase(chain_objs):
                                consumed.update(idx_chain)
                                break

                i += words_skipped

            # ----------------------------------------------------------
            # B. ORPHAN IMAGES
            # ----------------------------------------------------------
            for img_idx, img in enumerate(images):
                if img_idx in claimed_images:
                    continue
                try:
                    if (img['x1'] - img['x0']) < 30 or (img['bottom'] - img['top']) < 30:
                        continue

                    print(f"  [DEBUG] Orphan Image Found: Index {img_idx}")

                    bbox   = (img['x0'], img['top'], img['x1'], img['bottom'])
                    crop   = page.within_bbox(bbox)
                    im_obj = crop.to_image(resolution=200).original

                    unmatched_name = f"unmatched_p{page_num+1}_{img_idx}.jpg"
                    save_path      = os.path.join(TEMP_DIR, unmatched_name)
                    im_obj.save(save_path)

                    nearby_text = []
                    img_bottom  = img['bottom']
                    for w in words:
                        # Look BELOW the orphan
                        if img_bottom < w['top'] < (img_bottom + 50):
                            if (w['x0'] < img['x1']) and (w['x1'] > img['x0']):
                                nearby_text.append(clean_ligatures(w['text']))

                    found_text = _smart_join(nearby_text) if nearby_text else "No text found immediately below"
                    print(f"    -> Text below orphan: {found_text}")

                    unmatched_data.append({
                        "path":       save_path,
                        "text_found": found_text,
                        "page":       page_num + 1,
                    })
                except Exception as e:
                    print(f"    [ERROR] Processing orphan {img_idx}: {e}")

    debug_dump_pua_chars()

    print(f"\n=== Scan summary ===")
    print(f"  Photos extracted: {len(results)}")
    print(f"  Orphan images (no name match found nearby): {len(unmatched_data)}")
    if match_method_counts:
        print(f"  Matches by method:")
        for method, count in sorted(match_method_counts.items(), key=lambda kv: -kv[1]):
            print(f"    {method}: {count}")
    if collisions:
        print(f"  [COLLISION] {len(collisions)} student ID(s) were matched more than once this scan "
              f"(a later match overwrote an earlier photo for the same ID):")
        for c in collisions:
            print(f"    ID {c['id']} — overwritten via '{c['matched_via']}' match")
    else:
        print(f"  No ID collisions detected.")

    print(f"--- Finished. Extracted {len(results)} photos. ---\n")
    return results, unmatched_data, collisions


def image_to_a4_pdf(upload):
    """
    Converts an image upload to a standard A4 PDF page (595x842 points).
    Centers and scales the image to fit the page.
    """
    # Standard A4 size in PDF points (72 DPI equivalent)
    # This prevents the page from appearing huge in the PDF viewer
    A4_W, A4_H = 595, 842
    
    try:
        img = Image.open(upload)
        # Ensure correct color mode
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # Calculate aspect ratio to 'contain' the image within A4
        width_ratio = A4_W / img.width
        height_ratio = A4_H / img.height
        scale = min(width_ratio, height_ratio)
        
        # New dimensions
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
            
        # Resize using high-quality resampling
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        # Create a blank white A4 canvas
        canvas = Image.new('RGB', (A4_W, A4_H), (255, 255, 255))
        
        # Paste image in the center
        x_offset = (A4_W - new_w) // 2
        y_offset = (A4_H - new_h) // 2
        canvas.paste(img, (x_offset, y_offset))
        
        # Save as PDF bytes
        buf = BytesIO()
        canvas.save(buf, format="PDF", resolution=72)
        return buf.getvalue()
        
    except Exception as e:
        st.error(f"Error converting image to PDF: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# UI — Medical Booklet Creator
# ─────────────────────────────────────────────────────────────────────────────

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Hide Streamlit toolbar & kill the chin gap ── */
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  #MainMenu,
  header { display: none !important; }
  [data-testid="stAppViewContainer"] > section > div:first-child { padding-top: 0 !important; }
  .block-container { padding-top: 0 !important; }

  /* ── Global background ── */
  [data-testid="stAppViewContainer"] { background: #f5f6fa; }
  [data-testid="stSidebar"] { display: none; }

  /* ── Tab styling ── */
  [data-testid="stTabs"] [role="tablist"] {
    gap: 4px;
    border-bottom: 2px solid #e2e5ee;
    padding-bottom: 0;
  }
  [data-testid="stTabs"] [role="tab"] {
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: #6b6f82 !important;
    padding: 8px 18px !important;
    border-radius: 6px 6px 0 0 !important;
    border: none !important;
    background: transparent !important;
  }
  [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #1a7f6e !important;
    border-bottom: 2px solid #1a7f6e !important;
    background: transparent !important;
  }

  /* ── Section headers ── */
  .section-head {
    font-size: 0.72rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #1a7f6e;
    margin: 28px 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid #d0ede9;
  }

  /* ── Upload cards ── */
  .upload-card {
    background: #ffffff;
    border: 1px solid #e2e5ee;
    border-left: 4px solid #1a7f6e;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 10px;
  }
  .upload-card.optional { border-left-color: #e8960a; }
  .upload-card-label { font-size: 0.82rem; font-weight: 600; color: #1a1d2e; margin-bottom: 4px; }
  .upload-card-desc { font-size: 0.76rem; color: #9295a8; margin-bottom: 10px; }
  .seqta-link {
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 0.75rem; font-weight: 500; color: #1a7f6e;
    text-decoration: none; background: #e8f7f4;
    border: 1px solid #a8ddd6; border-radius: 5px;
    padding: 3px 9px; margin-bottom: 8px;
  }
  .seqta-link:hover { background: #d0ede9; }

  /* ── Options / step badges ── */
  .step-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; background: #1a7f6e; color: white;
    border-radius: 50%; font-size: 0.75rem; font-weight: 650;
    margin-right: 8px; flex-shrink: 0;
  }
  .step-row { display: flex; align-items: center; margin-bottom: 6px; }
  .step-label { font-size: 0.95rem; font-weight: 600; color: #1a1d2e; }
  .options-card {
    background: #ffffff; border: 1px solid #e2e5ee;
    border-radius: 10px; padding: 18px 20px; margin-bottom: 12px;
  }
  .options-card-title {
    font-size: 0.8rem; font-weight: 650; color: #1a7f6e;
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px;
  }

  /* ── Footer ── */
  .mbc-footer {
    margin-top: 48px; padding-top: 16px;
    border-top: 1px solid #e2e5ee; text-align: center;
    font-size: 0.75rem; color: #b0b3c4;
  }

  /* ── Feature selection cards — full-card clickable buttons ── */
  /* Target via :has() on the column that contains the unique marker span */
  [data-testid="stColumn"]:has(#fc-booklet-marker) [data-testid="stBaseButton-secondary"] > button,
  [data-testid="stColumn"]:has(#fc-group-marker) [data-testid="stBaseButton-secondary"] > button,
  [data-testid="stColumn"]:has(#fc-attach-marker) [data-testid="stBaseButton-secondary"] > button {
    all: unset !important;
    display: block !important;
    width: 100% !important;
    background: #ffffff !important;
    border: 2px solid #e2e5ee !important;
    border-radius: 14px !important;
    padding: 32px 28px !important;
    text-align: center !important;
    cursor: pointer !important;
    transition: border-color 0.18s, box-shadow 0.18s, transform 0.14s !important;
    color: #6b6f82 !important;
    font-size: 0.84rem !important;
    line-height: 1.65 !important;
    box-sizing: border-box !important;
    min-height: 220px !important;
    white-space: pre-line !important;
    letter-spacing: 0 !important;
  }
  [data-testid="stColumn"]:has(#fc-booklet-marker) [data-testid="stBaseButton-secondary"] > button p,
  [data-testid="stColumn"]:has(#fc-group-marker) [data-testid="stBaseButton-secondary"] > button p,
  [data-testid="stColumn"]:has(#fc-attach-marker) [data-testid="stBaseButton-secondary"] > button p {
    margin: 0 !important;
    padding: 0 !important;
  }
  [data-testid="stColumn"]:has(#fc-booklet-marker) [data-testid="stBaseButton-secondary"] > button:hover,
  [data-testid="stColumn"]:has(#fc-group-marker) [data-testid="stBaseButton-secondary"] > button:hover,
  [data-testid="stColumn"]:has(#fc-attach-marker) [data-testid="stBaseButton-secondary"] > button:hover {
    border-color: #1a7f6e !important;
    box-shadow: 0 6px 24px rgba(26,127,110,0.13) !important;
    transform: translateY(-3px) !important;
    color: #1a1d2e !important;
  }
</style>""", unsafe_allow_html=True)


st.markdown("""<style>
  [data-testid="stFileUploader"] { background: #fafcfb; border-radius: 8px; }
  div[data-testid="stCheckbox"] label { font-size: 0.88rem !important; }
  div[data-testid="stSelectbox"] label { font-size: 0.88rem !important; }
  .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1a7f6e, #2563a8) !important;
    border: none !important; border-radius: 8px !important;
    font-weight: 600 !important; padding: 10px 28px !important;
    font-size: 0.9rem !important; color: #ffffff !important;
  }
  .stButton > button[kind="primary"]:hover { opacity: 0.92 !important; }
  .stButton > button:not([kind="primary"]) { border-radius: 7px !important; font-size: 0.86rem !important; }
  [data-testid="stTextInput"] input {
    border-radius: 8px !important; font-size: 0.9rem !important; border-color: #d0ede9 !important;
  }
  [data-testid="stTextInput"] input:focus {
    border-color: #1a7f6e !important; box-shadow: 0 0 0 2px rgba(26,127,110,0.15) !important;
  }
  div.stAlert { border-radius: 8px !important; font-size: 0.85rem !important; }
  [data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, #1a7f6e, #2563a8) !important;
  }



  /* ── ID Matcher output box ── */
  .group-output-wrap {
    background: #f0faf8;
    border: 2px solid #a8ddd6;
    border-radius: 10px;
    padding: 16px 18px;
    margin-top: 12px;
  }
  .group-output-label {
    font-size: 0.75rem; font-weight: 700; color: #1a7f6e;
    text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 8px;
  }
  .seqta-instruction {
    background: #fff8e6;
    border-left: 4px solid #e8960a;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 0.82rem;
    color: #7a5a00;
    margin-top: 10px;
  }
</style>
""", unsafe_allow_html=True)

# ── Header + Menu ─────────────────────────────────────────────────────────────
# Strategy: paint the page top with a CSS body::before gradient band.
# The Streamlit columns row sits ON TOP of it with a negative top margin
# to pull it up into the painted area. Zero React issues, zero div injection.


# ── Sticky header: columns row that sticks to top on scroll ─────────────────
# `position: sticky` works within Streamlit's layout flow — no fighting the
# layout engine, no chin gap, no scroll-away. The gradient is on the row itself.

st.markdown("""
<style>
  /* ── Make the very first horizontal block sticky ── */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child {
    position: sticky !important;
    top: 0 !important;
    z-index: 999 !important;
  }
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child > div {
    background: linear-gradient(135deg, #1a7f6e 0%, #2563a8 100%) !important;
    padding: 12px 24px !important;
    margin: -4rem -4rem 0 -4rem !important;
  }
  /* Text in the title column */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child p {
    color: #ffffff !important;
    margin: 0 !important;
    line-height: 1.3 !important;
  }
  /* Caption under title */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child
      [data-testid="stCaptionContainer"] p {
    color: rgba(255,255,255,0.55) !important;
    font-size: 0.72rem !important;
    font-weight: 400 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
  }
  /* ⋯ popover button ghost style */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child
      [data-testid="stPopover"] > button {
    background: rgba(255,255,255,0.15) !important;
    border: 1px solid rgba(255,255,255,0.32) !important;
    color: #ffffff !important;
    border-radius: 7px !important;
    font-size: 1rem !important;
    padding: 6px 12px !important;
    min-height: unset !important;
    line-height: 1 !important;
    float: right !important;
  }
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child
      [data-testid="stPopover"] > button:hover {
    background: rgba(255,255,255,0.26) !important;
  }

  /* ── Popover dropdown panel ── */
  [data-testid="stPopoverBody"] {
    padding: 6px 0 10px !important;
    min-width: 195px !important;
  }
  /* Section label */
  [data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.67rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    color: #9295a8 !important;
    padding: 10px 14px 3px 14px !important;
    margin: 0 !important;
    line-height: 1 !important;
  }
  /* Action buttons */
  [data-testid="stPopoverBody"] [data-testid="stButton"] > button {
    all: unset !important;
    display: flex !important;
    align-items: center !important;
    width: 100% !important;
    padding: 9px 14px !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    color: #1a1d2e !important;
    cursor: pointer !important;
    box-sizing: border-box !important;
    line-height: 1.2 !important;
  }
  [data-testid="stPopoverBody"] [data-testid="stButton"] > button:hover {
    background: #f2f3f7 !important;
    color: #1a7f6e !important;
  }
  /* Divider */
  [data-testid="stPopoverBody"] hr {
    margin: 5px 0 !important;
    border: none !important;
    border-top: 1px solid #ecedf2 !important;
  }
  /* Caption */
  [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] {
    padding: 6px 14px 2px !important;
    color: #9295a8 !important;
    font-size: 0.76rem !important;
    line-height: 1.55 !important;
  }
</style>
""", unsafe_allow_html=True)

_h1, _h2 = st.columns([11, 1])
with _h1:
    st.markdown("**📋 Medical Booklet Tools**")
    st.caption("Created by Thomas van Sant")
with _h2:
    with st.popover("•••"):
        st.markdown("Actions")
        if st.button("↩  Start Over", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
        if st.button("⏹  Close the App", use_container_width=True):
            st.session_state._show_close = not st.session_state.get("_show_close", False)
            st.rerun()
        st.divider()
        st.markdown("Info")
        if st.button("❓  Help", use_container_width=True):
            st.session_state._show_help = not st.session_state.get("_show_help", False)
            st.rerun()
        if st.button("ℹ  About", use_container_width=True):
            st.session_state._show_about = not st.session_state.get("_show_about", False)
            st.rerun()
        if st.button("🛠  Debug Log", use_container_width=True):
            st.session_state._show_debug_log = not st.session_state.get("_show_debug_log", False)
            st.rerun()

if st.session_state.get("_show_close"):
    st.info("**To close the app:** Switch to the Terminal window that opened when you launched, press **Ctrl + C**, then close Terminal.", icon="⏹")

if st.session_state.get("_show_help"):
    with st.container(border=True):
        st.markdown("**Quick help**")
        st.markdown("""
- **Launch:** Double-click **Open Medical Booklet.command** in `Documents/medical-booklet`, or click it in your Dock.
- **Stop the app:** Find the Terminal window and press **Ctrl + C**.
- **Seqta data:** Both required files come from [Seqta Reporting](https://teach.friends.tas.edu.au/studentSummary/reporting).
- **Start fresh:** Use **Start Over** in the ••• menu to clear all uploads and begin again.
        """)
        if st.button("✕  Close help"):
            st.session_state._show_help = False
            st.rerun()

if st.session_state.get("_show_about"):
    with st.container(border=True):
        st.markdown("**📋 Medical Booklet Creator**")
        st.markdown("Generates student profile PDFs for excursion and field activity planning — medical information, emergency contacts, learning support, swimming ability and dietary requirements.")
        st.caption("Created by Thomas van Sant · Friends' School")
        if st.button("✕  Close"):
            st.session_state._show_about = False
            st.rerun()

if st.session_state.get("_show_debug_log"):
    with st.container(border=True):
        st.markdown("**🛠 Debug Log**")
        st.caption(
            "A running record of everything the app has done this session — "
            "photo matching, swimming/dietary/contact matching, and any errors. "
            "If something looks wrong, filter for a surname below, or use "
            "**Prepare full report** and send it to the developer."
        )

        _anon_map = _build_anonymization_map(st.session_state.get("df_final"))
        _anon_on = st.checkbox(
            "🔒  Anonymise student names/IDs (recommended before sharing)",
            value=True,
            key="_debug_log_anon",
            disabled=not _anon_map,
            help=(
                "Replaces every real surname, first name, preferred name, and "
                "student ID with a code (e.g. \"Surname014\"). The same real "
                "value always gets the same code, so patterns like two "
                "students colliding on one photo are still visible — the "
                "actual names just aren't."
                if _anon_map else
                "No roster is loaded yet this session, so there's nothing to anonymise."
            ),
        )

        if _anon_map:
            _risk_findings = _scan_name_pattern_risks(st.session_state.get("df_final"), _anon_map)
            with st.expander(f"⚠️  Name pattern risk-scan — {len(_risk_findings)} flagged (anonymised)"):
                st.caption(
                    "A proactive scan of the roster for the kinds of character "
                    "patterns that have caused problems here before — ligature "
                    "sequences a PDF font can render as a single odd glyph "
                    "(like the \"tt\"/\"ti\" in \"Matti\"), accented characters, "
                    "hyphens, and apostrophes. Nothing here is necessarily a bug "
                    "— it's a shortlist of names worth double-checking if a "
                    "photo or record ever goes missing. Codes only, no real names."
                )
                if not _risk_findings:
                    st.write("No flagged patterns in the current roster.")
                else:
                    from collections import defaultdict
                    _by_cat = defaultdict(list)
                    for f in _risk_findings:
                        _by_cat[f["category"]].append(f)
                    for cat, items in _by_cat.items():
                        st.markdown(f"**{cat}** ({len(items)})")
                        for it in items:
                            st.markdown(f"- `{it['code']}` ({it['field']}) — {it['detail']}")

        _dbg_filter = st.text_input(
            "Filter (e.g. a surname — if anonymising, use the code shown in the log)",
            key="_debug_log_filter",
        )

        _full_log = "".join(st.session_state.get("_debug_log_chunks", []))
        _display_log = _anonymize_text(_full_log, _anon_map) if _anon_on else _full_log
        _shown_log = _display_log
        if _dbg_filter.strip():
            _shown_log = "\n".join(
                line for line in _display_log.splitlines()
                if _dbg_filter.strip().lower() in line.lower()
            ) or "(no lines matched that filter)"

        st.text_area("Log output", _shown_log, height=320, key="_debug_log_display")

        _dcol1, _dcol2, _dcol3 = st.columns([1, 1, 1])
        with _dcol1:
            if st.button("📋  Prepare full report", use_container_width=True):
                st.session_state._debug_report_ready = True
                st.rerun()
        with _dcol2:
            if st.button("🗑  Clear log", use_container_width=True):
                st.session_state._debug_log_chunks = []
                st.session_state._debug_log_total_len = 0
                st.rerun()
        with _dcol3:
            if st.button("✕  Close", use_container_width=True):
                st.session_state._show_debug_log = False
                st.session_state._debug_report_ready = False
                st.rerun()

        if st.session_state.get("_debug_report_ready"):
            _report_log = _anonymize_text(_full_log, _anon_map) if _anon_on else _full_log
            _risk_section = ""
            if _anon_map:
                _risk_items = _scan_name_pattern_risks(st.session_state.get("df_final"), _anon_map)
                _risk_lines = [f"- {it['code']} ({it['field']}) — {it['category']}: {it['detail']}" for it in _risk_items]
                _risk_section = (
                    "\n\n" + ("-" * 60) + "\nNAME PATTERN RISK-SCAN (anonymised)\n" + ("-" * 60) + "\n"
                    + ("\n".join(_risk_lines) if _risk_lines else "(none flagged)")
                )
            _report = (
                _gather_environment_info()
                + _risk_section
                + "\n\n" + ("-" * 60) + "\nLOG\n" + ("-" * 60) + "\n" + _report_log
            )
            if _anon_on and _anon_map:
                st.success("Names and student IDs below have been replaced with codes.", icon="🔒")
            st.text_area(
                "Full report — select all (Cmd/Ctrl+A) and copy, then paste into an email or message",
                _report, height=400, key="_debug_report_display",
            )


SEQTA_URL = "https://teach.friends.tas.edu.au/studentSummary/reporting"

if "attachments" not in st.session_state: st.session_state.attachments = {}
if "project_title" not in st.session_state: st.session_state.project_title = ""
if "auto_downloaded_plans" not in st.session_state: st.session_state.auto_downloaded_plans = {}
if "auto_downloaded_plan_files" not in st.session_state: st.session_state.auto_downloaded_plan_files = {}
if "manual_plan_uploads" not in st.session_state: st.session_state.manual_plan_uploads = {}

# ── Build only the tabs that are needed for the current feature ──────────────
_active_feature = st.session_state.get("active_feature", None)

if _active_feature == "booklet":
    _tab_labels = ["  🏠 Home  ", "  📋 Booklet Setup  ", "  ⚙️ Process & Generate  "]
    _tabs = st.tabs(_tab_labels)
    t0, t1, t2 = _tabs
    t3 = t4 = None
elif _active_feature == "group":
    _tab_labels = ["  🏠 Home  ", "  🔗 ID Matcher  "]
    _tabs = st.tabs(_tab_labels)
    t0, t3 = _tabs
    t1 = t2 = t4 = None
elif _active_feature == "attachments":
    _tab_labels = ["  🏠 Home  ", "  📎 Attachment Downloader  "]
    _tabs = st.tabs(_tab_labels)
    t0, t4 = _tabs
    t1 = t2 = t3 = None
else:
    _tab_labels = ["  🏠 Home  "]
    _tabs = st.tabs(_tab_labels)
    t0 = _tabs[0]
    t1 = t2 = t3 = t4 = None

# ── Auto-tab-switch helper (injected as a hidden iframe via st.components) ────
def _inject_tab_click(tab_index):
    """Reliably clicks a Streamlit tab by index after the DOM has settled.
    Uses a time-based nonce so Streamlit always treats this as new content
    and re-renders the iframe — otherwise identical HTML is skipped on rerun."""
    import time
    nonce = int(time.time() * 1000)
    fn = f"clickTab_{tab_index}_{nonce}"
    st.components.v1.html(f"""
    <script>
        var _attempts_{nonce} = 0;
        function {fn}() {{
            var tabs = window.parent.document.querySelectorAll('[data-testid="stTabs"] [role="tab"]');
            if (tabs.length > {tab_index} && tabs[{tab_index}]) {{
                tabs[{tab_index}].click();
            }} else if (_attempts_{nonce} < 20) {{
                _attempts_{nonce}++;
                setTimeout({fn}, 100);
            }}
        }}
        setTimeout({fn}, 200);
    </script>
    """, height=0)

# Auto-switch: → Booklet Setup tab (index 1 when feature=booklet)
if st.session_state.get("_go_setup"):
    st.session_state._go_setup = False
    _inject_tab_click(1)

# Auto-switch: → ID Matcher tab (index 1 when feature=group)
if st.session_state.get("_go_group"):
    st.session_state._go_group = False
    _inject_tab_click(1)

# Auto-switch: → Attachment Downloader tab (index 1 when feature=attachments)
if st.session_state.get("_go_attach"):
    st.session_state._go_attach = False
    _inject_tab_click(1)

# Auto-switch: → Process & Generate tab (index 2 when feature=booklet)
if st.session_state.get("_active_tab") == 1:
    st.session_state._active_tab = None
    _inject_tab_click(2)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 0 — HOME / FEATURE SELECTOR
# ═══════════════════════════════════════════════════════════════════════════════
with t0:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### What would you like to do?")
    st.markdown("Choose a tool below to get started.")
    st.markdown("<br>", unsafe_allow_html=True)

    home_col1, home_col2, home_col3 = st.columns(3)

    with home_col1:
        # Hidden marker lets CSS target and style this column's button as a card
        st.markdown('<span id="fc-booklet-marker" style="display:none"></span>', unsafe_allow_html=True)
        if st.button(
            "📋\n\n**Medical Booklet Creator**\n\nGenerate student medical profile PDFs for excursions — medical info, emergency contacts, swimming ability, dietary requirements and more.",
            use_container_width=True,
            key="home_booklet_btn"
        ):
            st.session_state.active_feature = 'booklet'
            st.session_state._go_setup = True
            st.rerun()

    with home_col2:
        # Hidden marker lets CSS target and style this column's button as a card
        st.markdown('<span id="fc-group-marker" style="display:none"></span>', unsafe_allow_html=True)
        if st.button(
            "🔗\n\n**ID Matcher**\n\nPaste a list of names, student IDs or emails and get back the matching value from the student list — ready to paste into SEQTA.",
            use_container_width=True,
            key="home_group_btn"
        ):
            st.session_state.active_feature = 'group'
            st.session_state._go_group = True
            st.rerun()

    with home_col3:
        st.markdown('<span id="fc-attach-marker" style="display:none"></span>', unsafe_allow_html=True)
        if st.button(
            "📎\n\n**Attachment Downloader**\n\nDownload every student's medical action plan from the portal and save them as a folder, named by student. Only needs the Student List CSV.",
            use_container_width=True,
            key="home_attach_btn"
        ):
            st.session_state.active_feature = 'attachments'
            st.session_state._go_attach = True
            st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SETUP
# ═══════════════════════════════════════════════════════════════════════════════
if t1 is not None:
 with t1:

    st.session_state.project_title = st.text_input(
        "Booklet title",
        st.session_state.project_title,
        placeholder="e.g. Year 9 Camp — March 2025"
    )

    # ── Required documents ────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Required — from Seqta</div>', unsafe_allow_html=True)

    col_a, col_b, col_b2 = st.columns(3)
    with col_a:
        st.markdown(f"""
        <div class="upload-card">
          <div class="upload-card-label">Student List CSV</div>
          <div class="upload-card-desc">Student data including medical, emergency and learning information.</div>
          <a class="seqta-link" href="{SEQTA_URL}" target="_blank">↗ Open in Seqta</a>
        </div>
        """, unsafe_allow_html=True)
        csv = st.file_uploader("Student List CSV", type="csv", label_visibility="collapsed")

    with col_b:
        st.markdown(f"""
        <div class="upload-card">
          <div class="upload-card-label">Student Photos PDF</div>
          <div class="upload-card-desc">Photo contact sheet exported from Seqta.</div>
          <a class="seqta-link" href="{SEQTA_URL}" target="_blank">↗ Open in Seqta</a>
        </div>
        """, unsafe_allow_html=True)
        photos = st.file_uploader("Student Photos PDF", type="pdf", label_visibility="collapsed")

    with col_b2:
        st.markdown(f"""
        <div class="upload-card">
          <div class="upload-card-label">Excursion Student Info PDF</div>
          <div class="upload-card-desc">The "Excursion contact &amp; medical info" report from Seqta — provides home address, phone numbers and parent/guardian contacts.</div>
          <a class="seqta-link" href="{SEQTA_URL}" target="_blank">↗ Open in Seqta</a>
        </div>
        """, unsafe_allow_html=True)
        seqta_contact_pdf = st.file_uploader("Excursion Student Info PDF", type="pdf", label_visibility="collapsed", key="seqta_contact_pdf_uploader")

    # ── Optional documents ────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Optional — from Paperly forms</div>', unsafe_allow_html=True)

    contact_csv = None  # replaced by Excursion Student Info PDF

    col_c, col_d, col_e, col_f = st.columns(4)
    with col_c:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Swimming Ability CSV</div>
          <div class="upload-card-desc">Adds swimming competency to each student profile. You can upload multiple files — they'll be combined automatically.</div>
        </div>
        """, unsafe_allow_html=True)
        swimming_csv_files = st.file_uploader("Swimming Ability CSV", type="csv", label_visibility="collapsed", accept_multiple_files=True)

    with col_d:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Dietary Requirements CSV</div>
          <div class="upload-card-desc">Adds dietary needs and generates a summary table. You can upload multiple files — they'll be combined automatically.</div>
        </div>
        """, unsafe_allow_html=True)
        dietary_csv_files = st.file_uploader("Dietary Requirements CSV", type="csv", label_visibility="collapsed", accept_multiple_files=True)

    with col_e:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Photo Permissions (CSV or Excel)</div>
          <div class="upload-card-desc">Adds photo permission status to each profile and generates a no-permission list. Upload either (or both): <strong>Paperly CSV</strong> responses, and/or an <strong>Excel (.xlsx) list of students WITHOUT photo permission</strong> (matched by Student ID — only students in your student list are used). You can upload multiple files — they'll be combined automatically.</div>
        </div>
        """, unsafe_allow_html=True)
        photo_perm_uploads = st.file_uploader("Photo Permissions (CSV or Excel)", type=["csv", "xlsx"], label_visibility="collapsed", accept_multiple_files=True)
        photo_perm_csv_files  = [f for f in (photo_perm_uploads or []) if f.name.lower().endswith('.csv')]
        photo_perm_xlsx_files = [f for f in (photo_perm_uploads or []) if f.name.lower().endswith('.xlsx')]

    with col_f:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">💊 Camp Medications CSV</div>
          <div class="upload-card-desc">From the Paperly camp medication form. Adds a medication administration log page to the booklet — only students with medications are shown. Also adds an OTC-medication permissions table (Antihistamine / Ibuprofen / Paracetamol) to each student's profile page. You can upload multiple files — they'll be combined automatically.</div>
        </div>
        """, unsafe_allow_html=True)
        camp_med_csv_files = st.file_uploader("Camp Medications CSV", type="csv", label_visibility="collapsed", key="camp_med_csv_uploader", accept_multiple_files=True)

    # ── Y8 Camp Data (optional) ────────────────────────────────────────────────
    st.markdown('<div class="section-head">Optional — Y8 Camp Data</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="upload-card optional">
      <div class="upload-card-label">🏕️ Y8 Camp Data (Updated_Leader_Overview.xlsx)</div>
      <div class="upload-card-desc">
        Export from the Y8 Camp Group Maker. When uploaded, enables the
        <strong>Y8 Preloaded Camp Groups</strong> sort option — auto-groups students
        by class and camp, and injects a Leader Survey Summary page into each booklet.
      </div>
    </div>
    """, unsafe_allow_html=True)
    y8_camp_file = st.file_uploader(
        "Y8 Camp Data Excel",
        type=["xlsx"],
        label_visibility="collapsed",
        key="y8_camp_uploader"
    )

    if y8_camp_file is not None:
        _y8_file_id = getattr(y8_camp_file, "file_id", y8_camp_file.name)
        if st.session_state.get("_y8_camp_file_id") != _y8_file_id:
            try:
                with st.spinner("Parsing Y8 camp data…"):
                    _y8_parsed = parse_y8_camp_excel(y8_camp_file)
                st.session_state.y8_camp_data    = _y8_parsed
                st.session_state._y8_camp_file_id = _y8_file_id
                st.success(f"✅ Y8 camp data loaded — {len(_y8_parsed)} students across "
                           f"{len(set(v['class'] for v in _y8_parsed.values()))} classes")
            except Exception as _e:
                st.error(f"Could not parse Y8 camp file: {_e}")
                st.session_state.y8_camp_data = {}
        else:
            # File unchanged — show the persistent loaded confirmation
            _y8 = st.session_state.y8_camp_data
            if _y8:
                st.success(f"✅ Y8 camp data loaded — {len(_y8)} students across "
                           f"{len(set(v['class'] for v in _y8.values()))} classes")
    # NOTE: No else-clear here. Switching to another tab causes y8_camp_file to be
    # None (the Setup tab isn't rendered), but the data in session_state must persist
    # so the Y8 option remains visible in Step 5. Data is only cleared via Start Over.

    if st.session_state.y8_camp_data:
        _y8 = st.session_state.y8_camp_data
        _classes = sorted(set(v['class'] for v in _y8.values()))
        _camps   = sorted(set(v['camp']  for v in _y8.values()))
        st.caption(f"🏕️ Loaded: classes {', '.join(_classes)}  ·  camps: {', '.join(_camps)}")

    # ── Y9 Camp Data (optional) ────────────────────────────────────────────────
    st.markdown('<div class="section-head">Optional — Y9 Camp Data</div>', unsafe_allow_html=True)
    # Bumping this number gives the two uploaders new keys, which empties them ("Clear Y9 camp data").
    _y9_ver = st.session_state.get("_y9_uploader_ver", 0)
    _y9_c1, _y9_c2 = st.columns(2)
    with _y9_c1:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">🏔️ Y9 Camp Survey (CSV)</div>
          <div class="upload-card-desc">
            The student survey export with the 1–10 ratings. Adds a <strong>Camp Leader Summary</strong>
            page to each group's booklet. Students are matched by email, then by name — upload the
            Student List CSV at the same time.
          </div>
        </div>
        """, unsafe_allow_html=True)
        y9_survey_file = st.file_uploader(
            "Y9 Camp Survey CSV", type="csv", label_visibility="collapsed",
            key=f"y9_survey_uploader_{_y9_ver}")
    with _y9_c2:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">🏔️ Y9 Camp Groups (CSV)</div>
          <div class="upload-card-desc">
            The week-by-week group allocation (student IDs, leaders and notes for each group). Enables the
            <strong>Y9 Preloaded Camp Groups</strong> sort option — one booklet per group.
          </div>
        </div>
        """, unsafe_allow_html=True)
        y9_groups_file = st.file_uploader(
            "Y9 Camp Groups CSV", type="csv", label_visibility="collapsed",
            key=f"y9_groups_uploader_{_y9_ver}")

    # Parse the groups file once per upload. As with Y8, there is deliberately no auto-clear when the
    # uploader is empty (the Setup tab isn't rendered while on another tab) — use "Clear Y9 camp data".
    if y9_groups_file is not None:
        _y9g_file_id = getattr(y9_groups_file, "file_id", y9_groups_file.name)
        if st.session_state.get("_y9_groups_file_id") != _y9g_file_id:
            try:
                with st.spinner("Parsing Y9 camp groups…"):
                    _y9g_parsed = parse_y9_groups_csv(y9_groups_file)
                if _y9g_parsed["groups"] and _y9g_parsed["id_to_group"]:
                    st.session_state.y9_groups_data = _y9g_parsed
                    st.session_state._y9_groups_file_id = _y9g_file_id
                else:
                    st.session_state.y9_groups_data = None
                    st.error("No groups or student IDs were found in the Y9 groups file. Each week needs a header "
                             "row of '<group name>, ID' column pairs with the student IDs listed underneath.")
            except Exception as _e:
                st.session_state.y9_groups_data = None
                st.error(f"Could not parse Y9 camp groups file: {_e}")

    _y9g_loaded = st.session_state.get("y9_groups_data")
    if _y9g_loaded:
        _y9g_weeks = list(dict.fromkeys(g["week_label"] for g in _y9g_loaded["groups"]))
        st.success(f"✅ Y9 camp groups loaded — {len(_y9g_loaded['groups'])} groups across "
                   f"{len(_y9g_weeks)} week(s), {len(_y9g_loaded['id_to_group'])} students")
        for _w in _y9g_loaded.get("warnings", []):
            st.warning(_w)
        if st.button("🗑️ Clear Y9 camp data", key="y9_clear_btn"):
            st.session_state.y9_groups_data = None
            st.session_state.y9_survey_matched = {}
            st.session_state.y9_survey_unmatched = []
            st.session_state.y9_survey_manual = {}
            st.session_state.pop("_y9_groups_file_id", None)
            st.session_state._y9_uploader_ver = _y9_ver + 1
            st.rerun()

    # ── File processing ────────────────────────────────────────────────────────
    if csv:
        df_temp = pd.read_csv(csv).fillna("")
        st.session_state.df = df_temp
        st.session_state.df_final = df_temp
        st.success("✅ Student list loaded")

    # ── Seqta Contact PDF ──────────────────────────────────────────────────────
    if seqta_contact_pdf and "df_final" in st.session_state:
        try:
            with st.spinner("Parsing Excursion Student Info PDF…"):
                _pdf_recs = parse_seqta_contact_pdf_app(seqta_contact_pdf)
            _sc_matched, _sc_unmatched, _sc_ambiguous = match_seqta_contacts_app(
                _pdf_recs, st.session_state.df_final
            )
            st.session_state.seqta_contact_matched   = _sc_matched
            # Store unmatched + ambiguous together with an index for manual matching
            _all_unmatched = _sc_unmatched + [r for r, _ in _sc_ambiguous]
            st.session_state.seqta_contact_unmatched = [
                dict(rec, _index=i) for i, rec in enumerate(_all_unmatched)
            ]
            st.session_state.seqta_contact_manual = {}
            n_m = len(_sc_matched); n_u = len(_all_unmatched)
            if n_u == 0:
                st.success(f"✅ Excursion PDF: all {n_m} students matched")
            else:
                st.warning(f"⚠️ Excursion PDF: {n_m} matched · {n_u} need manual matching in Process tab")
        except Exception as e:
            st.error(f"Error parsing Excursion PDF: {e}")
    elif seqta_contact_pdf and "df_final" not in st.session_state:
        st.warning("Upload the Student List CSV at the same time as the Excursion PDF.")

    if swimming_csv_files:
        collated = collate_csvs(swimming_csv_files)
        if collated:
            st.session_state.swimming_csv = collated
            n = len(swimming_csv_files)
            label = f"{n} file{'s' if n > 1 else ''} combined" if n > 1 else "1 file"
            st.success(f"✅ Swimming ability CSV loaded ({label})")

    if dietary_csv_files:
        collated = collate_csvs(dietary_csv_files)
        if collated:
            st.session_state.dietary_csv = collated
            n = len(dietary_csv_files)
            label = f"{n} file{'s' if n > 1 else ''} combined" if n > 1 else "1 file"
            st.success(f"✅ Dietary requirements CSV loaded ({label})")

    if photo_perm_csv_files:
        collated = collate_csvs(photo_perm_csv_files)
        if collated:
            st.session_state.photo_perm_csv = collated
            n = len(photo_perm_csv_files)
            label = f"{n} file{'s' if n > 1 else ''} combined" if n > 1 else "1 file"
            st.success(f"✅ Photo permissions CSV loaded ({label})")

    if photo_perm_xlsx_files:
        noperm_df = read_no_photo_permission_xlsx(photo_perm_xlsx_files)
        if noperm_df is not None:
            st.session_state.photo_noperm_df = noperm_df
            n = len(photo_perm_xlsx_files)
            label = f"{n} files combined" if n > 1 else "1 file"
            st.success(f"✅ No-photo-permission Excel list loaded ({label}, {len(noperm_df)} rows)")

    if camp_med_csv_files:
        collated = collate_csvs(camp_med_csv_files)
        if collated:
            st.session_state.camp_med_csv = collated
            n = len(camp_med_csv_files)
            label = f"{n} file{'s' if n > 1 else ''} combined" if n > 1 else "1 file"
            st.success(f"✅ Camp medications CSV loaded ({label})")

    # ── Y9 camp survey (1–10 ratings) ─────────────────────────────────────────
    if y9_survey_file is not None:
        if "df_final" not in st.session_state:
            st.warning("Upload the Student List CSV at the same time as the Y9 survey so students can be matched.")
        else:
            _y9s_sig = (getattr(y9_survey_file, "file_id", y9_survey_file.name), len(st.session_state.df_final))
            if st.session_state.get("_y9_survey_sig") != _y9s_sig:
                try:
                    with st.spinner("Parsing and matching Y9 survey…"):
                        _y9_recs, _y9_info = parse_y9_survey_csv(y9_survey_file)
                        _y9_m, _y9_u, _y9_stats = match_y9_survey(_y9_recs, st.session_state.df_final)
                    st.session_state.y9_survey_matched   = _y9_m
                    st.session_state.y9_survey_unmatched = _y9_u
                    st.session_state.y9_survey_manual    = {}
                    st.session_state.y9_survey_missing   = _y9_info.get("missing", [])
                    st.session_state._y9_survey_sig      = _y9s_sig
                except Exception as _e:
                    st.error(f"Could not read Y9 survey file: {_e}")
    _y9_sm = st.session_state.get("y9_survey_matched") or {}
    _y9_su = st.session_state.get("y9_survey_unmatched") or []
    if _y9_sm or _y9_su:
        if _y9_su:
            st.warning(f"⚠️ Y9 survey: {len(_y9_sm)} students matched · {len(_y9_su)} need manual matching in the Process tab")
        else:
            st.success(f"✅ Y9 survey: all {len(_y9_sm)} students matched")
        if st.session_state.get("y9_survey_missing"):
            st.warning("Couldn't find these survey questions (those columns will show '–'): "
                       + ", ".join(st.session_state.y9_survey_missing))

    if photos:
        path = os.path.join(TEMP_DIR, "photos.pdf")
        with open(path, "wb") as f: f.write(photos.getbuffer())
        st.session_state.photo_pdf = path
        st.success("✅ Photos loaded")

    # ── Navigate to Process & Generate ───────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()
    ready = "df_final" in st.session_state and "photo_pdf" in st.session_state and "seqta_contact_matched" in st.session_state
    if ready:
        if st.button("\u25b6\u2002 Process & Generate \u2192", type="primary", use_container_width=True):
            st.session_state._active_tab = 1
            st.rerun()
    else:
        st.button("\u25b6\u2002 Process & Generate \u2192", type="primary", use_container_width=True, disabled=True)
        st.caption("Upload all three required files above to continue.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PROCESS & GENERATE
# ═══════════════════════════════════════════════════════════════════════════════
if t2 is not None:
 with t2:

    if "df_final" not in st.session_state or "photo_pdf" not in st.session_state:
        st.info("Upload a Student List CSV and Photos PDF in the Setup tab first.")


    if "df_final" in st.session_state and "photo_pdf" in st.session_state:
        df_final = st.session_state.df_final
        photo_pdf_path = st.session_state.photo_pdf

        # ── Step 1: Analyse ───────────────────────────────────────────────────────
        st.markdown('<div class="section-head">Step 1 — Analyse photos</div>', unsafe_allow_html=True)

        if st.button("Scan & Match Photos", type="primary"):
            with st.spinner("Scanning PDF and matching photos to students…"):
                results, unmatched, collisions = extract_photos_geometric(photo_pdf_path, df_final)
                st.session_state.auto_matches = results
                st.session_state.unmatched_data = unmatched
                st.session_state.photo_collisions = collisions
                st.session_state.extraction_done = True
                st.session_state.manual_selections = {}
                st.session_state.detected_plans = detect_medical_plans(df_final)

                if 'swimming_csv' in st.session_state:
                    contact_data = st.session_state.get('contact_csv_df', None)
                    swim_matched, swim_unmatched = match_swimming_ability(df_final, st.session_state.swimming_csv, contact_data)
                    st.session_state.swimming_matched = swim_matched
                    st.session_state.swimming_unmatched = swim_unmatched
                    st.session_state.swimming_manual_selections = {}

                if 'dietary_csv' in st.session_state:
                    dietary_matched, dietary_unmatched = match_dietary_requirements(df_final, st.session_state.dietary_csv)
                    st.session_state.dietary_matched = dietary_matched
                    st.session_state.dietary_unmatched = dietary_unmatched
                    st.session_state.dietary_manual_selections = {}

                if has_photo_permission_data():
                    perm_map = compute_photo_permissions(df_final)
                    st.session_state.photo_permissions_map = perm_map

                if 'camp_med_csv' in st.session_state:
                    camp_matched, camp_unmatched = match_camp_medications(df_final, st.session_state.camp_med_csv)
                    st.session_state.camp_medication_matched   = camp_matched
                    st.session_state.camp_medication_unmatched = camp_unmatched
                    st.session_state.camp_medication_manual    = {}
                    st.session_state.camp_permissions_matched  = match_camp_permissions(df_final, st.session_state.camp_med_csv)

                st.rerun()

        if st.session_state.get("extraction_done", False):

            # ── Step 2: Review photos ─────────────────────────────────────────────
            st.markdown('<div class="section-head">Step 2 — Review matches</div>', unsafe_allow_html=True)

            student_options = ["(Skip)"]
            name_to_id_map = {}
            id_to_name_map = {}
            for _, row in df_final.iterrows():
                sid = str(row[COLS['student_id']])
                label = f"{row[COLS['surname']]}, {row[COLS['first_name']]} ({sid})"
                student_options.append(label)
                name_to_id_map[label] = sid
                id_to_name_map[sid] = f"{row[COLS['first_name']]} {row[COLS['surname']]}"

            # ── Collision warning ───────────────────────────────────────────
            # If the same student ID got a photo assigned to it more than
            # once in this scan, an earlier (possibly correct) photo was
            # silently overwritten — usually because two same-surname
            # students' labels both resolved to one of them. Surface this
            # directly rather than relying on someone noticing a photo is
            # wrong or missing after the fact.
            _collisions = st.session_state.get("photo_collisions", [])
            if _collisions:
                with st.expander(
                    f"🚨  {len(_collisions)} possible photo mix-up(s) detected — review before generating booklets",
                    expanded=True,
                ):
                    st.warning(
                        "The same student was matched to a photo more than once during this scan. "
                        "That usually means two different photo labels in the PDF (often a shared "
                        "surname) both resolved to this one student — so their real photo may be "
                        "wrong, and whoever they were confused with may have no photo at all. "
                        "Please check both students below."
                    )
                    for c in _collisions:
                        _name = id_to_name_map.get(c["id"], c["id"])
                        st.markdown(f"**{_name}** (ID: {c['id']}) — matched via *{c['matched_via']}*")
                        _ccol1, _ccol2 = st.columns(2)
                        with _ccol1:
                            st.caption("Photo that was overwritten:")
                            if os.path.exists(c["previous_path"]):
                                st.image(c["previous_path"], width=120)
                        with _ccol2:
                            st.caption("Photo currently assigned:")
                            if os.path.exists(c["new_path"]):
                                st.image(c["new_path"], width=120)
                        st.caption(
                            "Also check whether another student with the same surname is now "
                            "missing a photo in the list below, and reassign manually if needed."
                        )
                        st.divider()

            # Photos
            n_auto = len(st.session_state.auto_matches)
            n_unmatched = len(st.session_state.unmatched_data)
            if n_unmatched > 0:
                with st.expander(f"⚠️  {n_unmatched} photos need manual matching  ({n_auto} matched automatically)", expanded=True):
                    for item in st.session_state.unmatched_data:
                        c1, c2 = st.columns([1, 4])
                        with c1: st.image(item['path'], width=90)
                        with c2:
                            st.caption(f"Page {item['page']} · Text nearby: *{item['text_found']}*")
                            sel = st.selectbox("Assign to student:", options=student_options, key=f"select_{item['path']}")
                            if sel != "(Skip)":
                                st.session_state.manual_selections[item['path']] = name_to_id_map[sel]
                            elif item['path'] in st.session_state.manual_selections:
                                del st.session_state.manual_selections[item['path']]
                        st.divider()
            else:
                st.success(f"✅ All {n_auto} photos matched automatically")

            # Swimming
            if 'swimming_csv' in st.session_state:
                total_swim_matched = len(st.session_state.get('swimming_matched', {}))
                total_swim_unmatched = len(st.session_state.get('swimming_unmatched', []))
                if total_swim_unmatched > 0:
                    with st.expander(f"⚠️  {total_swim_unmatched} swimming records need manual matching", expanded=True):
                        st.caption("These records couldn't be matched automatically — please assign them below.")
                        for item in st.session_state.swimming_unmatched:
                            c1, c2 = st.columns([1, 3])
                            with c1:
                                st.markdown(f"**{item['student_name']}**")
                            with c2:
                                color_map = {'swim-cannot': '🔴', 'swim-weak': '🟠', 'swim-ok': '🟢', 'swim-none': '⚪'}
                                ability_color = get_swimming_display_color(item['ability'])
                                st.markdown(f"{color_map.get(ability_color, '⚪')} {item['ability']}")
                                sel = st.selectbox("Assign to student:", options=student_options, key=f"swim_select_{item['index']}")
                                if sel != "(Skip)":
                                    st.session_state.swimming_manual_selections[item['index']] = name_to_id_map[sel]
                                elif item['index'] in st.session_state.swimming_manual_selections:
                                    del st.session_state.swimming_manual_selections[item['index']]
                            st.divider()
                else:
                    st.success(f"✅ All {total_swim_matched} swimming records matched automatically")

                # Students in the student list with NO swimming record (after manual matches)
                _swim_have = set(st.session_state.get('swimming_matched', {}).keys())
                _swim_have.update(st.session_state.get('swimming_manual_selections', {}).values())
                _swim_missing = [sid for sid in id_to_name_map if sid not in _swim_have]
                if _swim_missing:
                    with st.expander(f"⚠️  {len(_swim_missing)} students have no swimming data", expanded=False):
                        st.caption("These students will show \"Data not recorded\" on their profile and a "
                                   "\"No swimming data\" symbol in the Quick Overview.")
                        for _sid in _swim_missing:
                            st.markdown(f"- {id_to_name_map[_sid]}")

            # Dietary
            if 'dietary_csv' in st.session_state:
                total_diet_matched = len(st.session_state.get('dietary_matched', {}))
                total_diet_unmatched = len(st.session_state.get('dietary_unmatched', []))
                if total_diet_unmatched > 0:
                    with st.expander(f"⚠️  {total_diet_unmatched} dietary records need manual matching", expanded=True):
                        st.caption("These records couldn't be matched automatically — please assign them below.")
                        for item in st.session_state.dietary_unmatched:
                            c1, c2 = st.columns([1, 3])
                            with c1:
                                st.markdown(f"**{item['student_name']}**")
                            with c2:
                                preview = item['dietary_req'][:100] + "…" if len(item['dietary_req']) > 100 else item['dietary_req']
                                st.markdown(f"🍽️ {preview}")
                                sel = st.selectbox("Assign to student:", options=student_options, key=f"dietary_select_{item['index']}")
                                if sel != "(Skip)":
                                    st.session_state.dietary_manual_selections[item['index']] = name_to_id_map[sel]
                                elif item['index'] in st.session_state.dietary_manual_selections:
                                    del st.session_state.dietary_manual_selections[item['index']]
                            st.divider()
                else:
                    st.success(f"✅ All {total_diet_matched} dietary records matched automatically")

            # ── Seqta contact manual matching ──────────────────────────────────
            _sc_unmatched = st.session_state.get('seqta_contact_unmatched', [])
            _sc_matched   = st.session_state.get('seqta_contact_matched', {})
            if _sc_unmatched:
                with st.expander(f"⚠️  {len(_sc_unmatched)} contact record(s) need manual matching  ({len(_sc_matched)} matched automatically)", expanded=True):
                    st.caption("These students were found in the Excursion PDF but could not be automatically matched. Assign each to the correct student.")
                    for _item in _sc_unmatched:
                        _idx = _item.get('_index', id(_item))
                        _c1, _c2 = st.columns([2, 3])
                        with _c1:
                            st.markdown(f"**PDF name:** {_item.get('surname','')} {_item.get('first_name','')}")
                            if _item.get('home_address'):
                                st.caption(f"📍 {_item['home_address']}")
                            for _g in _item.get('guardians', []):
                                _phones = ' · '.join(filter(None, [_g.get('mobile'), _g.get('home'), _g.get('work')]))
                                st.caption(f"{_g.get('relationship','')}: {_g.get('name','')}  {_phones}")
                        with _c2:
                            _sel = st.selectbox("Assign to student:", options=student_options, key=f"sc_sel_{_idx}")
                            if _sel != "(Skip)":
                                st.session_state.seqta_contact_manual[_idx] = name_to_id_map[_sel]
                            elif _idx in st.session_state.seqta_contact_manual:
                                del st.session_state.seqta_contact_manual[_idx]
                        st.divider()
            elif _sc_matched:
                st.success(f"✅ All {len(_sc_matched)} contact records matched automatically")

            # Photo permissions summary
            if has_photo_permission_data():
                perm_map = st.session_state.get('photo_permissions_map', {})
                no_count = sum(1 for v in perm_map.values() if v == 'No')
                nr_count = sum(1 for v in perm_map.values() if v == 'No Response')
                yes_count = sum(1 for v in perm_map.values() if v == 'Yes')
                if no_count + nr_count > 0:
                    if st.session_state.get('photo_perm_csv') is None:
                        # Excel no-permission list only: every student is either listed (declined) or not
                        st.warning(f"📷 Photo Permissions: {no_count} declined (from Excel list) · {yes_count} not listed")
                    else:
                        st.warning(f"📷 Photo Permissions: {yes_count} Yes · {no_count} No · {nr_count} No Response")
                else:
                    st.success(f"✅ Photo Permissions: All {yes_count} students have given permission")
                _np_stats = st.session_state.get('photo_noperm_stats')
                if _np_stats and st.session_state.get('photo_noperm_df') is not None:
                    _by_name = f" ({_np_stats['by_name']} matched by name)" if _np_stats['by_name'] else ""
                    st.caption(
                        f"📷 No-permission Excel list: {_np_stats['matched']} of {_np_stats['listed']} "
                        f"listed students are in this student list and marked No{_by_name}."
                    )

            # Camp medications matching status
            if 'camp_med_csv' in st.session_state:
                camp_matched_st   = st.session_state.get('camp_medication_matched', {})
                camp_unmatched_st = st.session_state.get('camp_medication_unmatched', [])
                if camp_unmatched_st:
                    with st.expander(f"⚠️  {len(camp_unmatched_st)} camp medication record(s) need manual matching  ({len(camp_matched_st)} matched automatically)", expanded=True):
                        st.caption("These medication submissions couldn't be matched to a student automatically.")
                        for item in camp_unmatched_st:
                            _ck = item['index']
                            _c1, _c2 = st.columns([2, 3])
                            with _c1:
                                st.markdown(f"**CSV name:** {item['student_name']}")
                                for _m in item['medications']:
                                    st.caption(f"💊 {_m[:80]}{'…' if len(_m)>80 else ''}")
                            with _c2:
                                _sel = st.selectbox("Assign to student:", options=student_options, key=f"camp_med_sel_{_ck}")
                                if _sel != "(Skip)":
                                    st.session_state.camp_medication_manual[_ck] = name_to_id_map[_sel]
                                elif _ck in st.session_state.camp_medication_manual:
                                    del st.session_state.camp_medication_manual[_ck]
                            st.divider()
                elif camp_matched_st:
                    st.success(f"✅ Camp Medications: {len(camp_matched_st)} student(s) with medication matched automatically")

            # Y9 survey manual matching
            _y9_sm_st = st.session_state.get('y9_survey_matched', {})
            _y9_su_st = st.session_state.get('y9_survey_unmatched', [])
            if _y9_su_st:
                with st.expander(f"⚠️  {len(_y9_su_st)} Y9 survey response(s) need manual matching  ({len(_y9_sm_st)} matched automatically)", expanded=True):
                    st.caption("These survey responses couldn't be matched to a student with certainty. Pick the correct student, or leave as (Skip) to leave them out.")
                    for _it in _y9_su_st:
                        _yk = _it['_index']
                        _c1, _c2 = st.columns([2, 3])
                        with _c1:
                            st.markdown(f"**Survey name:** {_it.get('name') or '(blank)'}")
                            _meta = " · ".join(x for x in [_it.get('email'), _it.get('house')] if x)
                            if _meta:
                                st.caption(_meta)
                            if _it.get('_suggest'):
                                st.caption(f"💡 Possible match: {_it['_suggest']['label']}")
                        with _c2:
                            _sel = st.selectbox("Assign to student:", options=student_options, key=f"y9_sel_{_yk}")
                            if _sel != "(Skip)":
                                st.session_state.y9_survey_manual[_yk] = name_to_id_map[_sel]
                            elif _yk in st.session_state.y9_survey_manual:
                                del st.session_state.y9_survey_manual[_yk]
                        st.divider()
            elif _y9_sm_st:
                st.success(f"✅ Y9 Survey: {len(_y9_sm_st)} student(s) matched automatically")

            # ── Step 3: Medical plans ─────────────────────────────────────────────
            st.markdown('<div class="section-head">Step 3 — Medical action plans</div>', unsafe_allow_html=True)

            detected = st.session_state.get('detected_plans', {})

            # ── Advanced Options (session cookie + auto-download) ─────────────────
            if detected:
                with st.expander("⚙️ Advanced Options — Bulk download / import plans"):
                    st.markdown("**Auto-download all plans using your portal session**")
                    st.caption(
                        "This uses your existing browser login to download action plans automatically. "
                        "Your credentials are never stored — only the temporary session value is used."
                    )

                    # Cookie name hint (Synweb/Seqta typically uses one of these)
                    PORTAL_HOST = CONFIG['app_settings'].get('school_portal_url', '')
                    portal_domain = PORTAL_HOST.replace("https://", "").replace("http://", "").split("/")[0]

                    st.markdown("**How to get your session cookie:**")
                    st.markdown(f"""
    1. Log into [{portal_domain}]({PORTAL_HOST}) in Chrome or Safari as normal
    2. Press **F12** to open DevTools (or right-click anywhere → **Inspect**)
    3. Click the **Application** tab (Chrome) or **Storage** tab (Safari)
    4. In the left panel: **Cookies** → click `{portal_domain}`
    5. Find the cookie named **`ASP.NET_SessionId`** (or `SEQTASESSION`)
    6. Click it and copy the **Value** column
    7. Paste it below
    """)
                    st.info("💡 The cookie expires when you log out of the portal. If auto-download fails, log back in and copy a fresh value.", icon="ℹ️")

                    col_cookie, col_name = st.columns([3, 1])
                    with col_cookie:
                        cookie_val = st.text_input(
                            "Session cookie value",
                            value=st.session_state.get("_portal_cookie", ""),
                            type="password",
                            placeholder="Paste cookie value here…",
                            key="portal_cookie_input"
                        )
                    with col_name:
                        cookie_name = st.text_input(
                            "Cookie name",
                            value=st.session_state.get("_portal_cookie_name", "ASP.NET_SessionId"),
                            placeholder="ASP.NET_SessionId",
                            key="portal_cookie_name_input"
                        )

                    if cookie_val:
                        st.session_state["_portal_cookie"] = cookie_val
                    if cookie_name:
                        st.session_state["_portal_cookie_name"] = cookie_name

                    n_plans_total = sum(len(plans) for plans in detected.values())
                    btn_label = f"⬇ Auto-download all {n_plans_total} plan{'s' if n_plans_total != 1 else ''}"

                    if not cookie_val:
                        st.button(btn_label, disabled=True, help="Paste your session cookie above first")
                    else:
                        if st.button(btn_label, type="primary"):
                            if "auto_downloaded_plans" not in st.session_state:
                                st.session_state.auto_downloaded_plans = {}

                            download_results = []
                            prog_bar = st.progress(0)
                            total_plans = n_plans_total
                            done = 0

                            for sid, plans in detected.items():
                                s_name = id_to_name_map.get(sid, sid)
                                for p_idx, plan in enumerate(plans):
                                    url = plan.get('url')
                                    if not url:
                                        download_results.append((s_name, plan['condition'], False, "No URL available"))
                                        done += 1
                                        prog_bar.progress(done / total_plans)
                                        continue

                                    file_obj, filename, error = auto_download_plan(
                                        url,
                                        cookie_val,
                                        cookie_name=cookie_name or "ASP.NET_SessionId"
                                    )

                                    if file_obj:
                                        # Store raw bytes + filename as a plain tuple so they
                                        # survive st.rerun() serialisation. BytesIO objects are
                                        # not reliably preserved across reruns in session_state.
                                        plan_key = f"{sid}_{p_idx}"
                                        if "auto_downloaded_plan_files" not in st.session_state:
                                            st.session_state.auto_downloaded_plan_files = {}
                                        file_obj.seek(0)
                                        st.session_state.auto_downloaded_plan_files[plan_key] = (file_obj.read(), filename)
                                        st.session_state.auto_downloaded_plans[plan_key] = {
                                            "filename": filename, "sid": sid, "condition": plan['condition']
                                        }
                                        download_results.append((s_name, plan['condition'], True, filename))
                                    else:
                                        download_results.append((s_name, plan['condition'], False, error))

                                    done += 1
                                    prog_bar.progress(done / total_plans)

                            prog_bar.empty()

                            # Show results summary
                            successes = [r for r in download_results if r[2]]
                            failures  = [r for r in download_results if not r[2]]

                            if successes:
                                st.success(f"✅ Downloaded {len(successes)} of {total_plans} plans successfully")
                            if failures:
                                st.warning(f"⚠️ {len(failures)} plan{'s' if len(failures) != 1 else ''} could not be downloaded:")
                                for s_name, condition, _, reason in failures:
                                    st.caption(f"• **{s_name}** — {condition}: {reason}")

                            if successes:
                                st.rerun()

                    # ── Save plans as a folder / import saved plans ───────────────
                    st.divider()
                    _id_to_sf = {str(r[COLS['student_id']]): (r[COLS['surname']], r[COLS['first_name']])
                                 for _, r in df_final.iterrows()}

                    # Everything currently held: manual uploads take priority over auto-downloads
                    # (same order as booklet generation).
                    _held = []
                    _auto_f = st.session_state.get("auto_downloaded_plan_files", {})
                    _man_f  = st.session_state.get("manual_plan_uploads", {})
                    for _sid, _plans in detected.items():
                        for _i, _pl in enumerate(_plans):
                            _src = _man_f.get(f"{_sid}_{_i}") or _auto_f.get(f"{_sid}_{_i}")
                            if _src and _src[0]:
                                _held.append((_sid, _i + 1, _pl['condition'], _src[0], _src[1]))
                    _extra_n = {_s: len(_p) for _s, _p in detected.items()}
                    for _e in st.session_state.get("manual_plans_store", []):
                        try:
                            _e['file'].seek(0)
                            _raw = _e['file'].read()
                            _e['file'].seek(0)
                        except Exception:
                            _raw = b""
                        if _raw:
                            _extra_n[_e['sid']] = _extra_n.get(_e['sid'], 0) + 1
                            _held.append((_e['sid'], _extra_n[_e['sid']], "Extra plan", _raw,
                                          getattr(_e['file'], 'name', 'plan.pdf')))

                    st.markdown("**📦 Save plans as a folder**")
                    if _held:
                        st.caption(
                            f"{len(_held)} plan file(s) are loaded. This saves them in a ZIP containing an "
                            f"`{PLAN_FOLDER_NAME}` folder, each file named with the student's ID and name "
                            f"(e.g. `12345__Smith_Jane__01_Anaphylaxis.pdf`). Unzip it and keep the folder — "
                            f"you can drop it back in below next time instead of downloading from the portal."
                        )
                        _zip_bytes, _zip_problems, _zip_repaired = build_plans_zip(_held, _id_to_sf)
                        if _zip_repaired:
                            st.caption(f"🔧 {len(_zip_repaired)} file(s) were cleaned up so they open normally: "
                                       + "; ".join(f"{n} ({why})" for n, why in _zip_repaired[:8])
                                       + (" …" if len(_zip_repaired) > 8 else ""))
                        if _zip_problems:
                            st.warning(
                                f"⚠️ {len(_zip_problems)} file(s) couldn't be turned into a PDF and may not open. "
                                "Re-download or replace them:\n\n"
                                + "\n".join(f"- `{n}` — {why}" for n, why in _zip_problems[:25])
                            )
                        st.download_button(
                            f"⬇ Download {len(_held)} action plan(s) (ZIP folder)",
                            data=_zip_bytes,
                            file_name=f"{PLAN_FOLDER_NAME}_{datetime.now().strftime('%Y-%m-%d')}.zip",
                            mime="application/zip",
                            key="plans_zip_download",
                        )
                    else:
                        st.caption("Nothing to save yet — auto-download the plans above (or upload some) first.")

                    st.divider()
                    st.markdown("**📂 Import saved plans** (alternative to downloading from the portal)")
                    st.caption(
                        "Drag in the whole saved folder, all the files inside it, or the ZIP. Files are linked to students "
                        "automatically using the student ID in each file name (falling back to the student's name). "
                        "PDF, PNG and JPG files are accepted."
                    )
                    if "_plan_import_reset" not in st.session_state:
                        st.session_state._plan_import_reset = 0
                    _imp_files = st.file_uploader(
                        "Saved action plans",
                        type=['pdf', 'png', 'jpg', 'jpeg', 'zip'],
                        accept_multiple_files=True,
                        key=f"plan_import_{st.session_state._plan_import_reset}",
                    )
                    if _imp_files and st.button(f"Link {len(_imp_files)} file(s) to students", type="primary", key="plan_import_btn"):
                        _files, _skipped = expand_plan_uploads([(f.name, f.getvalue()) for f in _imp_files])
                        _occupied = {k for k, v in _auto_f.items() if v and v[0]} | {k for k, v in _man_f.items() if v and v[0]}
                        _assign, _unmatched = link_imported_plan_files(_files, detected, df_final, _occupied)
                        _linked, _extras = 0, 0
                        for _a in _assign:
                            if _a['slot'] is not None:
                                _k = f"{_a['sid']}_{_a['slot']}"
                                st.session_state.auto_downloaded_plan_files[_k] = (_a['data'], _a['name'])
                                st.session_state.auto_downloaded_plans[_k] = {
                                    "filename": _a['name'], "sid": _a['sid'],
                                    "condition": _a['condition'], "source": "import"}
                                st.session_state.manual_plan_uploads.pop(_k, None)  # imported file wins
                                _linked += 1
                            else:
                                _dup = False
                                for _e in st.session_state.manual_plans_store:
                                    if _e['sid'] == _a['sid'] and getattr(_e['file'], 'name', '') == _a['name'] \
                                            and _e['file'].getbuffer().nbytes == len(_a['data']):
                                        _dup = True
                                        break
                                if not _dup:
                                    _b = BytesIO(_a['data'])
                                    _b.name = _a['name']
                                    st.session_state.manual_plans_store.append({
                                        'sid': _a['sid'], 'name': id_to_name_map.get(_a['sid'], _a['sid']), 'file': _b})
                                    _extras += 1
                        st.session_state._plan_import_report = {
                            "linked": _linked, "extras": _extras, "unmatched": _unmatched, "skipped": _skipped,
                            "students": len({a['sid'] for a in _assign}),
                        }
                        st.session_state._plan_import_reset += 1
                        st.rerun()

                    _rep = st.session_state.get("_plan_import_report")
                    if _rep:
                        _tot = _rep['linked'] + _rep['extras']
                        if _tot:
                            st.success(f"✅ Linked {_tot} file(s) to {_rep['students']} student(s)"
                                       + (f" ({_rep['extras']} added as extra plans)" if _rep['extras'] else ""))
                        if _rep['unmatched']:
                            st.warning(f"{len(_rep['unmatched'])} file(s) couldn't be linked to a student — "
                                       "check the student ID is at the start of the name, or add them under "
                                       "'Add a plan manually': " + ", ".join(_rep['unmatched'][:15])
                                       + (" …" if len(_rep['unmatched']) > 15 else ""))
                        if _rep['skipped']:
                            st.caption(f"Ignored {len(_rep['skipped'])} unsupported file(s): "
                                       + ", ".join(_rep['skipped'][:10]) + (" …" if len(_rep['skipped']) > 10 else ""))

            # ── Per-student plan list ─────────────────────────────────────────────
            if "manual_plan_uploads" not in st.session_state:
                st.session_state.manual_plan_uploads = {}

            if detected:
                for sid, plans in detected.items():
                    s_name = id_to_name_map.get(sid, sid)
                    with st.container():
                        st.markdown(f"**{s_name}**")
                        for p_idx, plan in enumerate(plans):
                            col1, col2 = st.columns([3, 2])
                            with col1:
                                st.markdown(f"**{plan['condition']}**")
                                if plan.get('url'):
                                    st.markdown(f"[↗ Open document]({plan['url']})")
                                plan_key = f"{sid}_{p_idx}"
                                ad = st.session_state.get("auto_downloaded_plans", {}).get(plan_key)
                                if ad:
                                    st.caption(f"✅ {'Imported' if ad.get('source') == 'import' else 'Auto-downloaded'}: {ad['filename']}")
                                elif st.session_state.manual_plan_uploads.get(plan_key):
                                    fname = st.session_state.manual_plan_uploads[plan_key][1]
                                    st.caption(f"✅ Uploaded: {fname}")
                            with col2:
                                upload_label = f"Upload {plan['condition']}"
                                existing_key = f"plan_upload_{sid}_{p_idx}"
                                plan_key = f"{sid}_{p_idx}"
                                if st.session_state.get("auto_downloaded_plans", {}).get(plan_key):
                                    upload_label = f"Replace {plan['condition']} ({'imported' if st.session_state['auto_downloaded_plans'][plan_key].get('source') == 'import' else 'auto-downloaded'})"
                                uploaded = st.file_uploader(upload_label, type=['pdf','png','jpg'], key=existing_key)
                                # Cache uploaded file as raw bytes so it survives button-click reruns.
                                # Only update the cache when a file is actually present — never clear it.
                                if uploaded is not None:
                                    try:
                                        uploaded.seek(0)
                                        raw = uploaded.read()
                                        if raw:  # only store if non-empty
                                            st.session_state.manual_plan_uploads[plan_key] = (raw, uploaded.name)
                                    except Exception:
                                        pass
                        st.divider()
            else:
                st.caption("No action plans detected in student data.")

            # Initialise the manual plans store
            if "manual_plans_store" not in st.session_state:
                st.session_state.manual_plans_store = []  # list of {'sid': ..., 'name': ..., 'file': ...}
            if "_manual_plan_reset" not in st.session_state:
                st.session_state._manual_plan_reset = 0

            with st.expander("Add a plan manually", expanded=bool(st.session_state.manual_plans_store)):
                st.caption("Select a student, upload a file, then click **Add Plan**. Repeat for each student.")

                # Show already-added plans
                if st.session_state.manual_plans_store:
                    st.markdown("**Plans queued:**")
                    to_remove = None
                    for i, entry in enumerate(st.session_state.manual_plans_store):
                        c1, c2 = st.columns([6, 1])
                        with c1:
                            st.markdown(f"✅ **{entry['name']}** — {entry['file'].name}")
                        with c2:
                            if st.button("✕", key=f"remove_manual_plan_{i}", help="Remove this plan"):
                                to_remove = i
                    if to_remove is not None:
                        st.session_state.manual_plans_store.pop(to_remove)
                        st.rerun()
                    st.divider()

                # Use reset counter in key so widgets clear after Add Plan
                reset_key = st.session_state._manual_plan_reset
                man_sel = st.selectbox(
                    "Select student",
                    ["(Select a student)"] + sorted(list(name_to_id_map.keys())),
                    key=f"man_sel_{reset_key}"
                )
                man_file = st.file_uploader(
                    "Upload file",
                    type=['pdf', 'png', 'jpg'],
                    key=f"manual_plan_file_{reset_key}"
                )

                if st.button("Add Plan", key="add_manual_plan_btn", type="primary"):
                    if man_sel == "(Select a student)":
                        st.warning("Please select a student first.")
                    elif man_file is None:
                        st.warning("Please upload a file first.")
                    else:
                        st.session_state.manual_plans_store.append({
                            'sid': name_to_id_map[man_sel],
                            'name': man_sel,
                            'file': man_file
                        })
                        st.session_state._manual_plan_reset += 1
                        st.rerun()

            # ── Step 4: Content options ───────────────────────────────────────────
            st.markdown('<div class="section-head">Step 4 — Content options</div>', unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<div class="options-card-title">Header details</div>', unsafe_allow_html=True)
                opt_year  = st.checkbox("Year level",    value=True)
                opt_roll  = st.checkbox("Roll group",    value=True)
                opt_house = st.checkbox("House",         value=True)
                opt_dob   = st.checkbox("Date of birth", value=True)
                opt_tutor = st.checkbox("Tutor",         value=True)
                opt_sid   = st.checkbox("Student ID",    value=True)

                has_swimming   = 'swimming_csv' in st.session_state
                has_dietary    = 'dietary_csv' in st.session_state
                has_photo_perm = has_photo_permission_data()

                if has_swimming or has_dietary or has_photo_perm:
                    st.markdown("---")
                    st.markdown('<div class="options-card-title">Additional data</div>', unsafe_allow_html=True)
                opt_swimming   = st.checkbox("Swimming ability",     value=True) if has_swimming   else False
                opt_dietary    = st.checkbox("Dietary requirements", value=True) if has_dietary    else False
                opt_photo_perm = st.checkbox("Photo permissions",    value=True) if has_photo_perm else False

            with col2:
                st.markdown('<div class="options-card-title">Profile sections</div>', unsafe_allow_html=True)
                opt_sec_med   = st.checkbox("Medical information",         value=True)
                opt_sec_emerg = st.checkbox("Emergency contacts",          value=True)
                opt_sec_docs  = st.checkbox("Medical contacts (doctors)",  value=True)
                opt_sec_learn = st.checkbox("Learning & support",          value=True)
                opt_sec_home  = st.checkbox("Home contacts",               value=True)

            # ── Camp Medication Log (only if CSV was uploaded) ────────────────────
            _has_camp_meds = bool(st.session_state.get('camp_medication_matched') or
                                  st.session_state.get('camp_medication_manual') or
                                  'camp_med_csv' in st.session_state)
            if _has_camp_meds:
                st.markdown('<div class="section-head">💊 Camp Medication Log</div>', unsafe_allow_html=True)
                _camp_matched_count = len(st.session_state.get('camp_medication_matched', {})) + \
                                      len(st.session_state.get('camp_medication_manual', {}))
                st.info(
                    f"A medication administration log page will be added to the booklet "
                    f"for **{_camp_matched_count} student(s)** with medications. "
                    f"Groups with no listed medications get a page saying so, with blank rows for staff to fill in. "
                    f"Set the number of camp days below so sign-off columns can be generated."
                )
                camp_days_input = st.number_input(
                    "Number of camp days",
                    min_value=1, max_value=14,
                    value=st.session_state.get('camp_days', 3),
                    step=1,
                    help="One sign-off column will be added per day (for date, time and staff initials).",
                    key="camp_days_input"
                )
                st.session_state.camp_days = int(camp_days_input)

            # ── Step 5: Sort & output ─────────────────────────────────────────────
            st.markdown('<div class="section-head">Step 5 — Sort & output</div>', unsafe_allow_html=True)

            col3, col4 = st.columns(2)
            with col3:
                _sort_options = [
                    "Alphabetical (Surname)", "Roll Group", "House", "Year Level", "Custom Groups"
                ]
                if st.session_state.get("y8_camp_data"):
                    _sort_options.append("🏕️ Y8 Preloaded Camp Groups")
                if (st.session_state.get("y9_groups_data") or {}).get("groups"):
                    _sort_options.append(_Y9_SORT_LABEL)
                sort_by = st.selectbox("Sort students by:", _sort_options)
            with col4:
                if sort_by == "Alphabetical (Surname)":
                    output_mode = "Single Document"
                    st.caption("Alphabetical sorting produces a single combined document.")
                elif sort_by == "Custom Groups":
                    output_mode = st.radio("Output:", ["Separate PDF per group (ZIP)", "Single combined PDF with dividers"])
                elif sort_by == "🏕️ Y8 Preloaded Camp Groups":
                    output_mode = st.radio(
                        "Output:",
                        ["12 Separate PDFs (One for each Class/Camp)", "1 Master PDF"]
                    )
                elif sort_by == _Y9_SORT_LABEL:
                    output_mode = st.radio(
                        "Output:",
                        ["Separate PDFs — one per group (ZIP)", "1 Master PDF (all groups, in file order)"]
                    )
                else:
                    output_mode = st.radio("Output:", ["Single Document", f"Split by {sort_by}"])

            if sort_by == _Y9_SORT_LABEL:
                _y9d_ui = st.session_state.get("y9_groups_data") or {}
                _y9_map_ui = _y9d_ui.get("id_to_group", {})
                _id_col_ui = COLS.get('student_id', 'Code')
                _list_ids_ui = {_norm_student_id(v): i for i, v in df_final[_id_col_ui].items()} \
                    if _id_col_ui in df_final.columns else {}
                _in_groups = [n for n in _list_ids_ui if n in _y9_map_ui]
                _not_in_groups = [n for n in _list_ids_ui if n not in _y9_map_ui]
                _not_in_list = [n for n in _y9_map_ui if n not in _list_ids_ui]
                st.caption(f"🏔️ {len(_in_groups)} of {len(_list_ids_ui)} students in the Student List are in a Y9 camp group.")
                if _not_in_list:
                    st.warning(f"{len(_not_in_list)} student ID(s) in the groups file were not found in the Student List "
                               f"and will be skipped: {', '.join(sorted(_not_in_list)[:20])}"
                               f"{' …' if len(_not_in_list) > 20 else ''}")
                if _not_in_groups and _in_groups:
                    st.caption(f"ℹ️ {len(_not_in_groups)} student(s) in the Student List aren't in any group "
                               f"and won't be included (e.g. other year levels).")

            # ── Custom Groups builder (only shown when Custom Groups is selected) ──
            if sort_by == "Custom Groups":
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown('<div class="section-head">Define Groups</div>', unsafe_allow_html=True)
                st.markdown(
                    '<p style="font-size:0.82rem;color:#6b6f82;margin-bottom:8px;">'
                    'Add named groups below. Paste student IDs or email addresses into each group '
                    '(separated by spaces, commas, semicolons, newlines — any mix).</p>',
                    unsafe_allow_html=True
                )

                # ── Add a new group ───────────────────────────────────────────
                with st.expander("➕  Add a new group", expanded=len(st.session_state.custom_groups) == 0):
                    cg_new_label = st.text_input(
                        "Group name",
                        placeholder="e.g. Bus 1, Activity A, Mr Smith's Group",
                        key="cg_new_label"
                    )
                    cg_new_ids = st.text_area(
                        "Student IDs or email addresses",
                        height=120,
                        placeholder="e.g.\n12345, 12346\nsmith.j@school.edu.au\n12347 12348",
                        key="cg_new_ids"
                    )
                    if st.button("Add Group", type="primary", key="cg_add_btn"):
                        if not cg_new_label.strip():
                            st.warning("Please enter a group name.")
                        elif not cg_new_ids.strip():
                            st.warning("Please paste some student IDs or emails.")
                        else:
                            tokens = re.split(r'[\s,;|\t]+', cg_new_ids.strip())
                            tokens = [t.strip() for t in tokens if t.strip()]
                            st.session_state.custom_groups.append({
                                "label": cg_new_label.strip(),
                                "identifiers": tokens
                            })
                            st.rerun()

                # ── Show existing groups ──────────────────────────────────────
                if st.session_state.custom_groups:
                    st.markdown(f"**{len(st.session_state.custom_groups)} group(s) defined:**")
                    for gi, grp in enumerate(st.session_state.custom_groups):
                        gcol1, gcol2 = st.columns([5, 1])
                        with gcol1:
                            st.markdown(
                                f"<div style='background:#f0f4ff;border:1px solid #c5cae9;border-radius:6px;"
                                f"padding:8px 12px;margin-bottom:6px;font-size:0.88rem'>"
                                f"<strong>{grp['label']}</strong> &nbsp;·&nbsp; "
                                f"<span style='color:#5c6bc0'>{len(grp['identifiers'])} identifier(s)</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                        with gcol2:
                            if st.button("🗑️", key=f"cg_remove_{gi}", help="Remove this group"):
                                st.session_state.custom_groups.pop(gi)
                                st.rerun()
                    if st.button("🗑️  Clear all groups", key="cg_clear_all"):
                        st.session_state.custom_groups = []
                        st.rerun()

                    # ── Check ungrouped students ──────────────────────────────
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("🔍  Check for ungrouped students", key="cg_ungrouped_btn"):
                        id_col    = COLS.get('student_id', 'Code')
                        fname_col = COLS.get('first_name', 'First name')
                        sname_col = COLS.get('surname', 'Surname')
                        email_col_ug = None
                        for _c in ["Email", "email", "Email address", "Email Address", "Student email", "EmailAddress"]:
                            if _c in df_final.columns:
                                email_col_ug = _c; break
                        if email_col_ug is None:
                            for _c in df_final.columns:
                                if "email" in _c.lower():
                                    email_col_ug = _c; break
                        all_idents = set()
                        for grp in st.session_state.custom_groups:
                            for tok in grp['identifiers']:
                                all_idents.add(tok.strip().lower())
                        ungrouped = []
                        for _, row in df_final.iterrows():
                            sid   = str(row.get(id_col, '')).strip()
                            email = str(row.get(email_col_ug, '')).strip().lower() if email_col_ug else ''
                            fname = str(row.get(fname_col, '')).strip()
                            sname = str(row.get(sname_col, '')).strip()
                            if sid.lower() not in all_idents and (not email or email not in all_idents):
                                ungrouped.append(f"{sname}, {fname} ({sid})")
                        st.session_state['cg_ungrouped'] = ungrouped
                        st.rerun()

                    if 'cg_ungrouped' in st.session_state:
                        ug = st.session_state['cg_ungrouped']
                        if ug:
                            st.warning(f"⚠️ {len(ug)} student(s) are not in any group:")
                            with st.expander(f"Show {len(ug)} ungrouped student(s)"):
                                for name in ug:
                                    st.markdown(f"<span style='font-size:0.82rem'>{name}</span>", unsafe_allow_html=True)
                        else:
                            st.success("✅ All students are assigned to a group.")
                else:
                    st.info("No groups defined yet — add one above.")

            st.markdown("")

            # ── Attachment review (optional — separate from generating) ───────
            st.markdown('<div class="options-card-title">Attachment review (optional)</div>', unsafe_allow_html=True)
            st.caption("Choose the checks you want, then click **Review attachments** to look over anything flagged. "
                       "Skip this and **Generate** simply includes every attachment.")
            _ac1, _ac2, _ac3 = st.columns([3, 1, 4])
            with _ac1:
                opt_scan_long = st.checkbox("Flag attachments longer than", value=True, key="opt_scan_long")
            with _ac2:
                opt_scan_pages = st.number_input("Pages", min_value=1, max_value=100, value=5, step=1,
                                                 key="opt_scan_pages", label_visibility="collapsed")
            with _ac3:
                st.markdown("<div style='padding-top:8px'>pages</div>", unsafe_allow_html=True)
            opt_scan_dupes = st.checkbox("Scan for duplicate uploads (same file name and size)", value=True, key="opt_scan_dupes")
            opt_scan_multi = st.checkbox("Scan for multiple action plans for the same medical condition", value=True, key="opt_scan_multi")

            _rvb1, _rvb2 = st.columns([1, 3])
            with _rvb1:
                _review_clicked = st.button("🔎 Review attachments", key="rv_start", use_container_width=True)

            if _review_clicked:
                if not (opt_scan_long or opt_scan_dupes or opt_scan_multi):
                    st.session_state._plan_review_note = "⚠️ Tick at least one check first."
                else:
                    with st.spinner("Checking attachments…"):
                        _rv_pm = build_plan_map()
                        _rv_issues = scan_plan_issues(_rv_pm, id_to_name_map, int(opt_scan_pages),
                                                      opt_scan_long, opt_scan_dupes, opt_scan_multi)
                    if not _rv_pm:
                        st.session_state._plan_review_note = "ℹ️ There are no attachments to review yet."
                    elif _rv_issues:
                        for _k in [k for k in st.session_state.keys() if str(k).startswith("rv_") and k != "rv_start"]:
                            del st.session_state[_k]
                        st.session_state._rv_thumbs = {}
                        st.session_state._rv_first = {}
                        st.session_state._plan_review = {"issues": _rv_issues}
                        st.session_state._plan_review_note = ""
                    else:
                        st.session_state._plan_review = None
                        st.session_state._plan_review_decisions = None
                        st.session_state._plan_review_note = "✅ Reviewed — nothing needs your attention."

            with _rvb2:
                _rv_saved = st.session_state.get("_plan_review_decisions") or {}
                if _rv_saved and not st.session_state.get("_plan_review"):
                    _sr, _st_ = summarise_plan_review(_rv_saved)
                    _sc1, _sc2 = st.columns([4, 1])
                    with _sc1:
                        st.markdown(f"<div style='padding-top:8px'>✅ Review saved — Generate will leave out "
                                    f"<b>{_sr}</b> file(s) and trim <b>{_st_}</b>.</div>", unsafe_allow_html=True)
                    with _sc2:
                        if st.button("Clear", key="rv_clear", help="Forget the review choices and include every attachment"):
                            st.session_state._plan_review_decisions = None
                            st.session_state._plan_review_note = ""
                            st.rerun()
                elif st.session_state.get("_plan_review_note"):
                    st.markdown(f"<div style='padding-top:8px'>{st.session_state._plan_review_note}</div>", unsafe_allow_html=True)

            render_plan_review_panel()

            st.markdown("")
            if st.button("Generate Medical Booklet", type="primary"):

                # ── Gather plans (plus any attachment-review choices the user saved) ──
                detected = st.session_state.get('detected_plans', {})
                plan_map = build_plan_map()
                _rv_dec = st.session_state.get("_plan_review_decisions") or {}
                if _rv_dec:
                    _rv_rem, _rv_trim, _rv_prob, _rv_stale = apply_plan_review(plan_map, _rv_dec)
                    if _rv_rem or _rv_trim:
                        st.info(f"Using your attachment review: {_rv_rem} file(s) left out, {_rv_trim} trimmed to selected pages.")
                    if _rv_stale:
                        st.warning(f"{_rv_stale} of your attachment review choice(s) no longer match the current files "
                                   f"(they've changed since the review). Run **Review attachments** again if you want them applied.")
                    for _p in _rv_prob:
                        st.warning(_p)

                # ── Prepare data maps (logic unchanged) ──────────────────────────
                final_photo_map = st.session_state.auto_matches.copy()
                for p, s in st.session_state.manual_selections.items(): final_photo_map[s] = p

                final_y9_scores = build_y9_final_scores()
                final_swimming_map = st.session_state.get('swimming_matched', {}).copy()
                if st.session_state.get('swimming_manual_selections'):
                    for swim_idx, student_id in st.session_state.swimming_manual_selections.items():
                        for item in st.session_state.swimming_unmatched:
                            if item['index'] == swim_idx:
                                final_swimming_map[student_id] = item['ability']
                                break

                final_dietary_map = st.session_state.get('dietary_matched', {}).copy()
                if st.session_state.get('dietary_manual_selections'):
                    for dietary_idx, student_id in st.session_state.dietary_manual_selections.items():
                        for item in st.session_state.dietary_unmatched:
                            if item['index'] == dietary_idx:
                                final_dietary_map[student_id] = item['dietary_req']
                                break

                # Re-run photo permissions matching at generate time so it always
                # uses the latest session state (e.g. Excursion PDF guardian data
                # that may have been uploaded after the last "Scan & Match Photos" run).
                if has_photo_permission_data():
                    final_photo_perm_map = compute_photo_permissions(df_final)
                    st.session_state.photo_permissions_map = final_photo_perm_map
                else:
                    final_photo_perm_map = st.session_state.get('photo_permissions_map', {}).copy()

                print(f"\n{'='*80}")
                print("SWIMMING ABILITY MAP FOR PDF GENERATION")
                print(f"{'='*80}")
                print(f"Total students with swimming data: {len(final_swimming_map)}")
                if final_swimming_map:
                    print("\nFirst 10 students with swimming ability:")
                    for idx, (sid, ability) in enumerate(list(final_swimming_map.items())[:10]):
                        print(f"  Student {sid}: {ability}")
                else:
                    print("⚠️  WARNING: No swimming abilities found!")
                    print("   Check that swimming CSV was uploaded and analyzed")
                print(f"{'='*80}\n")

                # ── Render (logic unchanged) ──────────────────────────────────────
                status = st.status("Generating booklet…", expanded=True)
                env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
                tpl = env.get_template("profiles.html")
                display_opts = {
                    "year": opt_year, "roll": opt_roll, "house": opt_house,
                    "dob": opt_dob, "tutor": opt_tutor, "sid": opt_sid,
                    "swimming": opt_swimming, "dietary": opt_dietary,
                    "photo_perm": opt_photo_perm
                }

                all_records = []
                total = len(df_final)

                # ── Animated adventure progress bar ──────────────────────────
                import time as _time
                _gen_start = _time.time()
                _adventures = [
                    ("🧗", "Scaling the medical data cliff…"),
                    ("🚣", "Paddling through emergency contacts…"),
                    ("🏕️", "Setting up camp in the learning support section…"),
                    ("🤿", "Diving into swimming ability records…"),
                    ("🧭", "Navigating the photo permissions maze…"),
                    ("🎒", "Packing the final booklet…"),
                ]
                _prog_placeholder = st.empty()

                def _render_progress(pct, elapsed_s, total_students):
                    stage_idx = min(int(pct * len(_adventures)), len(_adventures) - 1)
                    emoji, label = _adventures[stage_idx]
                    bar_filled = int(pct * 30)
                    bar_empty  = 30 - bar_filled
                    bar_str    = "█" * bar_filled + "░" * bar_empty
                    if pct > 0.02 and elapsed_s > 0:
                        est_total = elapsed_s / pct
                        remaining = max(0, est_total - elapsed_s)
                        if remaining < 60:
                            eta = f"~{int(remaining)+1}s left"
                        else:
                            eta = f"~{int(remaining/60)+1}m left"
                    else:
                        eta = "calculating…"
                    done = int(pct * total_students)
                    _prog_placeholder.markdown(
                        f"""<div style="font-family:monospace;background:#f8f9fa;border:1px solid #dee2e6;
                        border-radius:8px;padding:14px 18px;margin:8px 0;line-height:1.8">
                        <div style="font-size:1.5rem;margin-bottom:4px">{emoji}</div>
                        <div style="font-size:0.85rem;color:#495057;margin-bottom:6px">{label}</div>
                        <div style="font-size:1.1rem;letter-spacing:1px;color:#1a7f6e">{bar_str}</div>
                        <div style="font-size:0.78rem;color:#868e96;margin-top:4px">
                            {done} / {total_students} students &nbsp;·&nbsp; {int(pct*100)}% &nbsp;·&nbsp; {eta}
                        </div></div>""",
                        unsafe_allow_html=True
                    )
                _render_progress(0, 0, total)

                for idx, (_, r) in enumerate(df_final.iterrows()):
                    _elapsed = _time.time() - _gen_start
                    _render_progress((idx + 1) / total, _elapsed, total)
                    sid = str(r[COLS['student_id']])
                    link_id = re.sub(r'[^a-zA-Z0-9]', '', sid) or f"row{idx}"

                    fname, sname = r[COLS['first_name']], r[COLS['surname']]
                    pref_col = COLS.get('preferred_name', 'Preferred name')
                    pname = str(r.get(pref_col, '')).strip()
                    if not pname or pname.lower() == 'nan':
                        pname = fname  # fall back to first name if no preferred name on file
                    dob = str(r.get('Birth date', r.get('Birth Date', ''))).strip()
                    try: dob = datetime.strptime(dob, '%Y-%m-%d').strftime('%d %b %Y')
                    except: pass
                    general_notes_text = str(r.get(COLS.get('general_notes', 'General notes'), ''))
                    gender_raw = str(r.get('Gender', r.get('gender', ''))).strip()
                    gender_lower = gender_raw.lower()
                    if gender_lower == 'm': gender = 'Male'
                    elif gender_lower == 'f': gender = 'Female'
                    else:
                        # For anything other than m/f, check General notes for a "Gender:" entry
                        gn_match = re.search(r'Gender:\s*\n?(.*?)(?:\n|$)', general_notes_text, re.IGNORECASE)
                        gn_value = gn_match.group(1).strip() if gn_match else ''
                        # The value might be blank on the same line and on the next line instead
                        if not gn_value:
                            gn_match2 = re.search(r'Gender:\s*\n([^\n]+)', general_notes_text, re.IGNORECASE)
                            gn_value = gn_match2.group(1).strip() if gn_match2 else ''
                        if gn_value and gn_value.lower() not in ('nan', ''):
                            gender = gn_value
                        elif gender_raw and gender_lower not in ('nan', ''):
                            gender = 'Other'
                        else:
                            gender = ''
                    house = str(r.get(COLS.get('house', 'House'), '')).strip()
                    tutor = parse_tutor(general_notes_text)
                    family_alert = parse_family_alert(general_notes_text)
                    year_lvl = str(r[COLS['year']])
                    roll_raw = str(r[COLS['rollgroup']])
                    roll = expand_rollgroup(roll_raw)  # full name e.g. "7 Mott"

                    raw_med   = str(r.get(COLS['medical_notes'], ""))
                    raw_emerg = str(r.get(COLS['emergency_notes'], ""))
                    parsed_med  = parse_medical_text(raw_med)
                    parsed_con  = parse_emergency_contacts(raw_emerg)
                    # Use Seqta PDF contacts (compulsory); fall back to CSV if missing
                    _pdf_rec = st.session_state.get('seqta_contact_matched', {}).get(sid)
                    if not _pdf_rec:
                        for _mi, _msid in st.session_state.get('seqta_contact_manual', {}).items():
                            if _msid == sid:
                                for _u in st.session_state.get('seqta_contact_unmatched', []):
                                    if _u.get('_index') == _mi:
                                        _pdf_rec = _u; break
                                break
                    parsed_home = home_contacts_from_pdf(_pdf_rec) if _pdf_rec else parse_home_contacts(r)

                    sections = []
                    layout = CONFIG["default_profile_layout"]
                    for sec in layout:
                        is_med = COLS['medical_notes'] in sec['fields']
                        is_emg = COLS['emergency_notes'] in sec['fields']
                        is_lrn = COLS['special_notes'] in sec['fields']
                        if is_med and opt_sec_med:
                            sections.append({"title": sec['section'], "type": "medical_cards", "content": parsed_med})
                        elif is_emg:
                            if family_alert:
                                sections.append({"title": "Family Alert", "type": "family_alert", "content": family_alert})
                            if opt_sec_home and (parsed_home['contacts'] or parsed_home['home_address'] or parsed_home['home_phone']):
                                sections.append({"title": "Home Contacts", "type": "home_contacts", "content": parsed_home})
                            if opt_sec_emerg:
                                sections.append({"title": sec['section'], "type": "emergency_grid", "content": parsed_con})
                            if opt_sec_docs:
                                d_col = "Doctor notes" if "Doctor notes" in r else COLS.get('doctor_details')
                                if d_col and d_col in r:
                                    sections.append({"title": "Medical Contacts", "type": "doctor_grid", "content": parse_doctors(str(r.get(d_col, "")))})
                        elif is_lrn and opt_sec_learn:
                            sections.append({"title": sec['section'], "type": "learning_support", "content": parse_learning_support(str(r.get(COLS['special_notes'], "")))})
                        elif not (is_med or is_emg or is_lrn):
                            vals = [str(r.get(f,"")).strip() for f in sec['fields'] if str(r.get(f,"")).strip()]
                            if not vals: vals = ["No data supplied."]
                            sections.append({"title": sec['section'], "type": "text", "content": vals})

                    embedded = []
                    if sid in plan_map:
                        for f in plan_map[sid]:
                            embedded.extend(convert_file_to_images(f))
                    if sid in st.session_state.attachments:
                        for f in st.session_state.attachments[sid]: embedded.extend(convert_file_to_images(f))

                    med_flags = detect_medical_flags(parsed_med, raw_med)
                    print(f"[quick overview flags] {sid} {sname}, {pname}: "
                          f"{[k for k, v in med_flags.items() if v] or 'none'} "
                          f"<- conditions: {[c['name'] for c in parsed_med] or 'none'}")

                    def _home_contact_display(idx):
                        contacts = parsed_home.get('contacts') if parsed_home else None
                        if not contacts or len(contacts) <= idx:
                            return None
                        c = contacts[idx]
                        phone = c.get('phone') or {}
                        return {
                            "name": c.get('name', ''),
                            "relation": c.get('relation', ''),
                            "phone_display": phone.get('display', ''),
                            "link": phone.get('link')
                        }

                    swim_ability    = str(final_swimming_map.get(sid, "") or "").strip() or "Data not recorded"
                    if opt_swimming and swim_ability == "Data not recorded":
                        print(f"[swimming] no swimming data for {sid} {sname}, {pname}")
                    swim_color      = get_swimming_display_color(swim_ability)
                    dietary_req     = final_dietary_map.get(sid, "No data given")
                    photo_perm_val  = final_photo_perm_map.get(sid, None)
                    otc_permissions = st.session_state.get('camp_permissions_matched', {}).get(sid) \
                        if 'camp_med_csv' in st.session_state else None

                    profile_obj = {
                        "id": sid, "link_id": link_id, "first": fname, "preferred": pname, "last": sname,
                        "year": year_lvl, "roll": roll, "house": house, "dob": dob, "gender": gender, "tutor": tutor,
                        "swimming": swim_ability, "swim_color": swim_color,
                        "dietary": dietary_req,
                        "photo_perm": photo_perm_val,
                        "otc_permissions": otc_permissions,
                        "photo": img_to_base64(final_photo_map.get(sid)),
                        "sections": sections, "attachments": embedded,
                        # Y8 camp survey data — None when not a camp booklet
                        "y8_camp": st.session_state.get("y8_camp_data", {}).get(sid, None),
                        # Y9 camp survey scores {label: '1'-'10'/'N/A'} — None when no survey response
                        "y9_scores": final_y9_scores.get(_norm_student_id(sid))
                    }
                    matrix_obj = {
                        "id": sid, "link_id": link_id, "name": f"{sname}, {pname}",
                        "gender": gender,
                        "home_contact_1": _home_contact_display(0),
                        "home_contact_2": _home_contact_display(1),
                        "asthma": med_flags['asthma'],
                        "allergy": med_flags['allergy'], "anaphylaxis": med_flags['anaphylaxis'],
                        "family_alert": bool(family_alert),
                        "photo_perm": photo_perm_val,
                        "swim_weak": "weak swimmer" in swim_ability.lower(),
                        "swim_cannot": "cannot swim" in swim_ability.lower(),
                        "swim_none": swim_ability.lower() == "data not recorded",
                        "swimming": swim_ability, "swim_color": swim_color
                    }
                    medical_obj = None
                    if parsed_med:
                        medical_obj = {"name": f"{pname} {sname}", "link_id": link_id, "conditions": parsed_med}

                    all_records.append({
                        "profile": profile_obj, "matrix": matrix_obj, "medical": medical_obj,
                        "sort_keys": {"alpha": sname + fname, "roll": roll, "house": house, "year": year_lvl}
                    })

                # ── Sort & group ──────────────────────────────────────────────
                status.write("Sorting & grouping…")

                def render_subset(records, title_suffix="", y8_camp_group=None, y9_group=None):
                    s_list   = [r['profile'] for r in records]
                    m_list   = [r['matrix']  for r in records]
                    med_list = [r['medical'] for r in records if r['medical']]
                    m_list.sort(key=lambda x: x['name'])
                    no_perm_list = [
                        s for s in s_list
                        if s.get('photo_perm') in ('No', 'No Response')
                    ] if display_opts.get('photo_perm') else []

                    # ── Build camp medication list for this subset ────────────────
                    _camp_med_all = st.session_state.get('camp_medication_matched', {}).copy()
                    # Apply manual matches
                    for _mk, _msid in st.session_state.get('camp_medication_manual', {}).items():
                        if _msid not in _camp_med_all:
                            for _u in st.session_state.get('camp_medication_unmatched', []):
                                if _u.get('index') == _mk:
                                    _fn = id_to_name_map.get(_msid, _msid)
                                    _camp_med_all[_msid] = {
                                        'name': _fn,
                                        'medications': _u['medications']
                                    }
                                    break
                    subset_sids = {r['profile']['id'] for r in records}
                    camp_medications_for_subset = [
                        {'name': _camp_med_all[_sid]['name'],
                         'medications': _camp_med_all[_sid]['medications']}
                        for _sid in [r['profile']['id'] for r in records]
                        if _sid in _camp_med_all
                    ] or None
                    _camp_days = st.session_state.get('camp_days', 3)

                    full_html = tpl.render(
                        title=f"{st.session_state.project_title} {title_suffix}",
                        date=datetime.now().strftime("%d %B %Y"),
                        students=s_list, matrix=m_list, medical_full=med_list,
                        no_perm_list=no_perm_list,
                        options=display_opts, mode="full",
                        student_count=len(s_list),
                        y8_camp_group=y8_camp_group,
                        y9_group=y9_group,
                        camp_medications=camp_medications_for_subset,
                        camp_med_uploaded=('camp_med_csv' in st.session_state),
                        camp_days=_camp_days,
                    )
                    return HTML(string=full_html).write_pdf()

                if sort_by == "Custom Groups":
                    # Build a sid/email → record lookup from all_records
                    id_col_cg = COLS.get('student_id', 'Code')
                    email_col_cg = None
                    for _c in ["Email", "email", "Email address", "Email Address", "Student email", "EmailAddress"]:
                        if _c in df_final.columns:
                            email_col_cg = _c; break
                    if email_col_cg is None:
                        for _c in df_final.columns:
                            if "email" in _c.lower():
                                email_col_cg = _c; break

                    # Map sid (lower) → record, and email (lower) → record
                    sid_to_rec   = {r['profile']['id'].lower(): r for r in all_records}
                    email_to_rec = {}
                    for _, row in df_final.iterrows():
                        em = str(row.get(email_col_cg, '')).strip().lower() if email_col_cg else ''
                        sid = str(row.get(id_col_cg, '')).strip().lower()
                        if em and em != 'nan' and sid in sid_to_rec:
                            email_to_rec[em] = sid_to_rec[sid]

                    def resolve_custom_group(identifiers):
                        seen = set(); recs = []
                        for tok in identifiers:
                            t = tok.strip().lower()
                            rec = sid_to_rec.get(t) or email_to_rec.get(t)
                            if rec and id(rec) not in seen:
                                recs.append(rec); seen.add(id(rec))
                        return recs

                    if not st.session_state.custom_groups:
                        status.update(label="⚠️ No groups defined", state="error", expanded=False)
                        st.warning("No custom groups were defined. Add groups in Step 5 before generating.")
                    elif "Separate" in output_mode:
                        _prog_placeholder.empty()
                        status.write("Generating separate PDFs…")
                        zip_buffer = BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            for grp in st.session_state.custom_groups:
                                grp_recs = resolve_custom_group(grp['identifiers'])
                                if not grp_recs:
                                    continue
                                pdf_data = render_subset(grp_recs, title_suffix=f"— {grp['label']}")
                                safe_name = re.sub(r'[^a-zA-Z0-9]', '_', grp['label'])
                                zf.writestr(f"Medical_Booklet_{safe_name}.pdf", pdf_data)
                        status.update(label="✅ All group booklets ready", state="complete", expanded=False)
                        st.download_button("⬇ Download Group Booklets (ZIP)", data=zip_buffer.getvalue(),
                                           file_name="Medical_Booklets_Groups.zip", mime="application/zip")
                    else:
                        _prog_placeholder.empty()
                        status.write("Generating combined PDF…")
                        writer = PdfWriter()
                        for grp in st.session_state.custom_groups:
                            grp_recs = resolve_custom_group(grp['identifiers'])
                            if not grp_recs:
                                continue
                            pdf_data = render_subset(grp_recs, title_suffix=f"— {grp['label']}")
                            reader = PdfReader(BytesIO(pdf_data))
                            for page in reader.pages:
                                writer.add_page(page)
                        combined_buf = BytesIO()
                        writer.write(combined_buf)
                        status.update(label="✅ Combined booklet ready", state="complete", expanded=False)
                        st.download_button("⬇ Download Combined Booklet", data=combined_buf.getvalue(),
                                           file_name="Medical_Booklet_Combined_Groups.pdf", mime="application/pdf")

                elif sort_by == "🏕️ Y8 Preloaded Camp Groups":
                    # Build groups keyed by "{Class} - {Camp}" e.g. "8A - Freycinet"
                    y8_groups = {}
                    for rec in all_records:
                        y8 = rec['profile'].get('y8_camp')
                        if y8:
                            gk = f"{y8['class']} - {y8['camp']}"
                            y8_groups.setdefault(gk, []).append(rec)

                    if not y8_groups:
                        status.update(label="⚠️ No students matched Y8 camp data", state="error", expanded=False)
                        st.warning(
                            "No students could be matched to the Y8 camp data. "
                            "Check that Student IDs in the Student List CSV match those in the camp Excel file."
                        )
                    elif "12 Separate" in output_mode:
                        _prog_placeholder.empty()
                        status.write("Generating separate camp PDFs…")
                        zip_buffer = BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            for g_name in sorted(y8_groups.keys()):
                                g_recs = y8_groups[g_name]
                                _camp = g_recs[0]['profile']['y8_camp']['camp']
                                pdf_data = render_subset(g_recs, title_suffix=f"— {g_name}", y8_camp_group=_camp)
                                safe_name = re.sub(r'[^a-zA-Z0-9]', '_', g_name)
                                zf.writestr(f"Medical_Booklet_{safe_name}.pdf", pdf_data)
                        status.update(label="✅ All camp booklets ready", state="complete", expanded=False)
                        st.download_button(
                            "⬇ Download Camp Booklets (ZIP)", data=zip_buffer.getvalue(),
                            file_name="Y8_Camp_Medical_Booklets.zip", mime="application/zip"
                        )
                    else:
                        _prog_placeholder.empty()
                        status.write("Generating master camp PDF…")
                        writer = PdfWriter()
                        for g_name in sorted(y8_groups.keys()):
                            g_recs = y8_groups[g_name]
                            _camp = g_recs[0]['profile']['y8_camp']['camp']
                            pdf_data = render_subset(g_recs, title_suffix=f"— {g_name}", y8_camp_group=_camp)
                            reader = PdfReader(BytesIO(pdf_data))
                            for page in reader.pages:
                                writer.add_page(page)
                        combined_buf = BytesIO()
                        writer.write(combined_buf)
                        status.update(label="✅ Master camp booklet ready", state="complete", expanded=False)
                        st.download_button(
                            "⬇ Download Master Camp Booklet", data=combined_buf.getvalue(),
                            file_name="Y8_Camp_Medical_Booklet_Master.pdf", mime="application/pdf"
                        )

                elif sort_by == _Y9_SORT_LABEL:
                    # One booklet per group in the Y9 groups file (file order: week, then group).
                    _y9d = st.session_state.get("y9_groups_data") or {}
                    _y9_map = _y9d.get("id_to_group", {})
                    _y9_by_key = {}
                    for rec in all_records:
                        gk = _y9_map.get(_norm_student_id(rec['profile']['id']))
                        if gk:
                            _y9_by_key.setdefault(gk, []).append(rec)
                    y9_groups = [
                        (g, sorted(_y9_by_key[g['key']], key=lambda r: r['sort_keys']['alpha']))
                        for g in _y9d.get("groups", []) if g['key'] in _y9_by_key
                    ]

                    if not y9_groups:
                        status.update(label="⚠️ No students matched Y9 camp groups", state="error", expanded=False)
                        st.warning(
                            "No students could be matched to the Y9 camp groups. "
                            "Check that the IDs in the groups file match the Code column in the Student List CSV."
                        )
                    elif "Separate" in output_mode:
                        _prog_placeholder.empty()
                        status.write("Generating separate Y9 group PDFs…")
                        zip_buffer = BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            for _i, (g, g_recs) in enumerate(y9_groups, 1):
                                pdf_data = render_subset(g_recs, title_suffix=f"— {g['week_label']}: {g['title']}", y9_group=g)
                                safe_name = re.sub(r'[^a-zA-Z0-9]+', '_', f"{g['week_label']} {g['title']}").strip('_')
                                zf.writestr(f"{_i:02d}_Medical_Booklet_{safe_name}.pdf", pdf_data)
                        status.update(label="✅ All Y9 group booklets ready", state="complete", expanded=False)
                        st.download_button(
                            "⬇ Download Y9 Group Booklets (ZIP)", data=zip_buffer.getvalue(),
                            file_name="Y9_Camp_Medical_Booklets.zip", mime="application/zip"
                        )
                    else:
                        _prog_placeholder.empty()
                        status.write("Generating master Y9 camp PDF…")
                        writer = PdfWriter()
                        for g, g_recs in y9_groups:
                            pdf_data = render_subset(g_recs, title_suffix=f"— {g['week_label']}: {g['title']}", y9_group=g)
                            reader = PdfReader(BytesIO(pdf_data))
                            for page in reader.pages:
                                writer.add_page(page)
                        combined_buf = BytesIO()
                        writer.write(combined_buf)
                        status.update(label="✅ Master Y9 camp booklet ready", state="complete", expanded=False)
                        st.download_button(
                            "⬇ Download Master Y9 Camp Booklet", data=combined_buf.getvalue(),
                            file_name="Y9_Camp_Medical_Booklet_Master.pdf", mime="application/pdf"
                        )

                elif sort_by == "Roll Group":
                    all_records.sort(key=lambda x: (str(x['sort_keys']['roll']), x['sort_keys']['alpha']))
                    group_key = 'roll'
                elif sort_by == "House":
                    all_records.sort(key=lambda x: (str(x['sort_keys']['house']), x['sort_keys']['alpha']))
                    group_key = 'house'
                elif sort_by == "Year Level":
                    all_records.sort(key=lambda x: (str(x['sort_keys']['year']), x['sort_keys']['alpha']))
                    group_key = 'year'
                else:
                    all_records.sort(key=lambda x: x['sort_keys']['alpha'])
                    group_key = 'alpha'

                if sort_by not in ("Custom Groups", "🏕️ Y8 Preloaded Camp Groups", _Y9_SORT_LABEL):
                    if "Split" in output_mode:
                        _prog_placeholder.empty()
                        status.write("Generating split PDFs…")
                        zip_buffer = BytesIO()
                        groups = {}
                        for r in all_records:
                            k = r['sort_keys'][group_key]
                            if not k: k = "Unknown"
                            if k not in groups: groups[k] = []
                            groups[k].append(r)
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            for g_name, g_records in groups.items():
                                safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(g_name))
                                pdf_data = render_subset(g_records, title_suffix=f"— {g_name}")
                                zf.writestr(f"Medical_Booklet_{safe_name}.pdf", pdf_data)
                        status.update(label="✅ All files generated", state="complete", expanded=False)
                        st.download_button("⬇ Download ZIP", data=zip_buffer.getvalue(),
                                           file_name="Medical_Booklets.zip", mime="application/zip")
                    else:
                        _prog_placeholder.empty()
                        status.write("Generating PDF…")
                        pdf_data = render_subset(all_records)
                        status.update(label="✅ Booklet ready", state="complete", expanded=False)
                        st.download_button("⬇ Download Medical Booklet", data=pdf_data,
                                           file_name="Medical_Booklet.pdf", mime="application/pdf")

# ── ID Matcher — Name-matching engine ───────────────────────────────────────
# Thresholds are deliberately conservative: two students can share a name,
# and typos can look close enough to a WRONG student to be dangerous if
# auto-accepted. When in doubt this always falls through to manual review
# rather than guessing.
_IDM_AUTO_THRESHOLD    = 0.97   # essentially "same spelling" after normalising
_IDM_AUTO_UNIQUE_GAP   = 0.03   # 2nd-best candidate must be at least this much lower to auto-accept
_IDM_SUGGEST_THRESHOLD = 0.72   # pre-select this candidate in the manual dropdown, but still require a click
_IDM_CANDIDATE_FLOOR   = 0.35   # below this, don't bother surfacing as a ranked suggestion
_IDM_MAX_CANDIDATES    = 6      # how many ranked suggestions to show per entry


def _idm_normalize_text(s):
    """Lowercase, strip accents/punctuation, collapse whitespace — so
    'Sofía O'Brien-Smith' and 'sofia obrien smith' compare equal."""
    s = (s or "").strip().lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r"[.,'’`_-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _idm_token_ratio(a, b):
    """difflib ratio between two normalised strings, comparing SORTED tokens
    so word order doesn't matter — 'Smith John' still matches 'John Smith'."""
    ta = " ".join(sorted(a.split()))
    tb = " ".join(sorted(b.split()))
    if not ta or not tb:
        return 0.0
    return difflib.SequenceMatcher(None, ta, tb).ratio()


def _idm_build_roster(df_gc):
    """One row_dict per CSV row: id/email/fname/pref/surname/year/roll,
    plus pre-normalised name fields for fast repeated scoring."""
    id_col    = COLS.get('student_id', 'Code')
    email_col = None
    for candidate in ["Email", "email", "Email address", "Email Address",
                       "Student email", "Student Email", "EmailAddress"]:
        if candidate in df_gc.columns:
            email_col = candidate
            break
    if email_col is None:
        for col in df_gc.columns:
            if "email" in col.lower():
                email_col = col
                break
    fname_col = COLS.get('first_name', 'First name')
    pref_col  = COLS.get('preferred_name', 'Preferred name')
    sname_col = COLS.get('surname', 'Surname')
    year_col  = COLS.get('year', 'Year')
    roll_col  = COLS.get('rollgroup', 'Rollgroup')

    roster = []
    for _, row in df_gc.iterrows():
        fname   = str(row.get(fname_col, "")).strip()
        pref    = str(row.get(pref_col, "")).strip()
        surname = str(row.get(sname_col, "")).strip()
        if not fname and not surname:
            continue
        rd = {
            "id": str(row.get(id_col, "")).strip(),
            "email": str(row.get(email_col, "")).strip() if email_col else "",
            "fname": fname,
            "pref": pref,
            "surname": surname,
            "year": str(row.get(year_col, "")).strip(),
            "roll": str(row.get(roll_col, "")).strip(),
        }
        rd["_norm_full"]  = _idm_normalize_text(f"{fname} {surname}")
        rd["_norm_pref"]  = _idm_normalize_text(f"{pref or fname} {surname}")
        rd["_norm_first"] = _idm_normalize_text(fname)
        rd["_norm_pref_only"] = _idm_normalize_text(pref or fname)
        rd["_norm_sur"]   = _idm_normalize_text(surname)
        roster.append(rd)
    return roster, email_col


def _idm_score_entry(entry, paste_format, roster):
    """Score one pasted entry against every roster row.
    entry is either a full-name string (paste_format == 'single')
    or a (first_field, surname_field) tuple (paste_format == 'two_col').
    Returns a list of (row_dict, score) sorted best-first."""
    scored = []
    if paste_format == "two_col":
        first_field, surname_field = entry
        n_first = _idm_normalize_text(first_field)
        n_sur   = _idm_normalize_text(surname_field)
        for rd in roster:
            first_score = max(
                _idm_token_ratio(n_first, rd["_norm_first"]),
                _idm_token_ratio(n_first, rd["_norm_pref_only"]),
            ) if n_first else 0.0
            sur_score = _idm_token_ratio(n_sur, rd["_norm_sur"]) if n_sur else 0.0
            # Both halves need to individually look right — a great surname
            # match with no first-name signal at all shouldn't count as strong.
            score = (first_score + sur_score) / 2 if n_first and n_sur else max(first_score, sur_score)
            if score >= _IDM_CANDIDATE_FLOOR:
                scored.append((rd, score))
    else:
        n_full = _idm_normalize_text(entry)
        for rd in roster:
            score = max(
                _idm_token_ratio(n_full, rd["_norm_full"]),
                _idm_token_ratio(n_full, rd["_norm_pref"]),
            )
            if score >= _IDM_CANDIDATE_FLOOR:
                scored.append((rd, score))

    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:_IDM_MAX_CANDIDATES]


def _idm_classify_entry(candidates):
    """Given ranked (row_dict, score) candidates, decide: auto-match,
    a pre-selected suggestion for manual review, or no suggestion at all."""
    if not candidates:
        return None, None  # (auto_row_or_None, suggested_row_or_None)
    top_row, top_score = candidates[0]
    if top_score >= _IDM_AUTO_THRESHOLD:
        second_score = candidates[1][1] if len(candidates) > 1 else 0.0
        if top_score - second_score >= _IDM_AUTO_UNIQUE_GAP:
            return top_row, None  # confidently unique — auto-match
    suggested = top_row if top_score >= _IDM_SUGGEST_THRESHOLD else None
    return None, suggested


def _idm_format_name(fname, pref, surname, fmt):
    """Format a student's name for ID Matcher Name output, per the chosen format."""
    fname   = (fname or "").strip()
    pref    = (pref or "").strip()
    surname = (surname or "").strip()
    effective_pref = pref if pref else fname  # fall back to first name if no preferred name on file

    if fmt == "First Name + Surname":
        return f"{fname} {surname}".strip()
    elif fmt == "Preferred Name + Surname":
        return f"{effective_pref} {surname}".strip()
    elif fmt == "First Name (Preferred Name) + Surname":
        if pref and pref.lower() != fname.lower():
            return f"{fname} ({pref}) {surname}".strip()
        return f"{fname} {surname}".strip()
    elif fmt == "Preferred Name":
        return effective_pref
    elif fmt == "Surname":
        return surname
    elif fmt == "First Name":
        return fname
    return f"{effective_pref} {surname}".strip()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ID MATCHER
# ═══════════════════════════════════════════════════════════════════════════════
if t3 is not None:
 with t3:

    st.markdown('<div class="section-head">ID Matcher</div>', unsafe_allow_html=True)
    st.markdown(
        'Choose what you\'re pasting in and what you want back, paste your list, and '
        '(optionally) upload a Student List CSV. The app will match them up — ready to paste into '
        '<a href="https://teach.friends.tas.edu.au/students/classes" target="_blank" style="color:#1a7f6e;font-weight:600">SEQTA</a>.',
        unsafe_allow_html=True
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Step 1: Input / Output type ───────────────────────────────────────────
    st.markdown('''<div class="section-head">Step 1 — What are you matching?</div>''', unsafe_allow_html=True)
    _idm_options = ["Name", "Student ID", "Email"]
    _IDM_NAME_FORMATS = [
        "Preferred Name + Surname",
        "First Name + Surname",
        "First Name (Preferred Name) + Surname",
        "Preferred Name",
        "Surname",
        "First Name",
    ]
    if 'idm_name_format' not in st.session_state:
        st.session_state.idm_name_format = "Preferred Name + Surname"

    idm_col1, idm_col2 = st.columns(2)
    with idm_col1:
        idm_input_type = st.selectbox(
            "I have a list of",
            options=_idm_options,
            index=_idm_options.index(st.session_state.idm_input_type),
            key="idm_input_type_box"
        )
    with idm_col2:
        idm_output_type = st.selectbox(
            "I want to get back",
            options=_idm_options,
            index=_idm_options.index(st.session_state.idm_output_type),
            key="idm_output_type_box"
        )
    st.session_state.idm_input_type = idm_input_type
    st.session_state.idm_output_type = idm_output_type

    # When the output is Name, let the user pick how it's formatted.
    if idm_output_type == "Name":
        idm_name_format = st.selectbox(
            "Name output format",
            options=_IDM_NAME_FORMATS,
            index=_IDM_NAME_FORMATS.index(st.session_state.idm_name_format),
            key="idm_name_format_box"
        )
        st.session_state.idm_name_format = idm_name_format
    else:
        idm_name_format = st.session_state.idm_name_format

    # Combinations wired up so far: Email ↔ Student ID, Student ID/Email → Name,
    # and now Name → Student ID / Email.
    _idm_supported_pairs = {
        ("Email", "Student ID"),
        ("Student ID", "Email"),
        ("Student ID", "Name"),
        ("Email", "Name"),
        ("Name", "Student ID"),
        ("Name", "Email"),
    }
    _idm_supported = (idm_input_type, idm_output_type) in _idm_supported_pairs
    if idm_input_type == idm_output_type:
        st.warning("Input and output are the same — pick two different fields.")
    elif not _idm_supported:
        st.info(f"🚧 {idm_input_type} → {idm_output_type} matching is coming soon.")

    # When the input is Name, ask how it's been pasted in — this materially
    # changes match reliability, so it's worth a conscious choice rather than guessing.
    _IDM_PASTE_FORMATS = [
        "One name per line (e.g. \"John Smith\")",
        "Two columns — pasted straight from a spreadsheet (First/Preferred Name, then Surname)",
    ]
    if 'idm_name_paste_format' not in st.session_state:
        st.session_state.idm_name_paste_format = _IDM_PASTE_FORMATS[0]

    if idm_input_type == "Name":
        idm_paste_format_label = st.radio(
            "How is your list formatted?",
            options=_IDM_PASTE_FORMATS,
            index=_IDM_PASTE_FORMATS.index(st.session_state.idm_name_paste_format),
            key="idm_name_paste_format_box"
        )
        st.session_state.idm_name_paste_format = idm_paste_format_label
        idm_paste_format = "two_col" if idm_paste_format_label.startswith("Two columns") else "single"
        if idm_paste_format == "two_col":
            st.caption(
                "Copy two adjacent columns (First or Preferred Name, then Surname) straight out of "
                "Excel or Google Sheets and paste below — the tab characters between columns are kept "
                "even though it looks like plain text, so each row is read as one student."
            )
    else:
        idm_paste_format = "single"

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Step 2: Paste the list ────────────────────────────────────────────────
    st.markdown(f'''<div class="section-head">Step 2 — Paste your list of {idm_input_type.lower()}s</div>''', unsafe_allow_html=True)
    if idm_input_type == "Name" and idm_paste_format == "two_col":
        st.markdown('<p style="font-size:0.82rem;color:#6b6f82;margin-bottom:8px;">Paste two columns copied from a spreadsheet — one student per row.</p>', unsafe_allow_html=True)
    elif idm_input_type == "Name":
        st.markdown('<p style="font-size:0.82rem;color:#6b6f82;margin-bottom:8px;">One full name per line.</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p style="font-size:0.82rem;color:#6b6f82;margin-bottom:8px;">Paste values separated by spaces, commas, semicolons, colons, pipes or newlines — any mix.</p>', unsafe_allow_html=True)
    _idm_placeholders = {
        "Name_single": "e.g.\nJohn Smith\nKate Jones\nTom Brown",
        "Name_two_col": "e.g. (paste columns from a spreadsheet)\nJohn\tSmith\nKate\tJones\nTom\tBrown",
        "Student ID": "e.g.\n1023, 1044\n1078",
        "Email": "e.g.\nsmith.j@school.edu.au, jones.k@school.edu.au\nbrown.t@school.edu.au",
    }
    _idm_placeholder_key = f"Name_{idm_paste_format}" if idm_input_type == "Name" else idm_input_type
    email_input = st.text_area(
        "Values to match",
        value=st.session_state.group_email_input,
        height=160,
        placeholder=_idm_placeholders.get(_idm_placeholder_key, ""),
        label_visibility="collapsed",
        key="gc_email_box"
    )
    st.session_state.group_email_input = email_input

    # Live preview for two-column paste, so a misaligned copy/paste is caught
    # before running the match rather than after.
    if idm_input_type == "Name" and idm_paste_format == "two_col" and email_input.strip():
        _preview_rows = []
        for _line in email_input.strip().split("\n"):
            if not _line.strip():
                continue
            _parts = _line.split("\t") if "\t" in _line else _line.split(",", 1)
            _first = _parts[0].strip() if len(_parts) > 0 else ""
            _sur = _parts[1].strip() if len(_parts) > 1 else ""
            _preview_rows.append({"First / Preferred Name": _first, "Surname": _sur})
        if _preview_rows:
            st.caption(f"📋 Preview — {len(_preview_rows)} row{'s' if len(_preview_rows) != 1 else ''} detected:")
            st.dataframe(pd.DataFrame(_preview_rows), height=min(250, 40 + 35 * len(_preview_rows)), use_container_width=True, hide_index=True)

    # ── Step 3: Student List CSV ──────────────────────────────────────────────
    st.markdown('''<div class="section-head">Step 3 — Student List CSV</div>''', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="upload-card">
      <div class="upload-card-label">Student List CSV</div>
      <div class="upload-card-desc">The same student list CSV from Seqta — used to look up the matching value.
      <br><a class="seqta-link" href="{SEQTA_URL}" target="_blank" style="margin-top:6px;display:inline-flex">↗ Open in Seqta</a></div>
    </div>
    """, unsafe_allow_html=True)
    gc_csv = st.file_uploader(
        "Student List CSV for ID matcher",
        type="csv",
        label_visibility="collapsed",
        key="gc_csv_uploader"
    )
    # If the booklet CSV is already loaded, offer to reuse it
    if gc_csv is None and "df_final" in st.session_state:
        st.caption("💡 A student list is already loaded from the Booklet Creator — it will be used automatically if no file is uploaded here.")

    st.markdown("<br>", unsafe_allow_html=True)
    run_gc = st.button("🔍  Find Matches", type="primary", key="gc_run_btn", disabled=not _idm_supported)

    if run_gc:
        # ── Parse the pasted list ────────────────────────────────────────────
        # Split on any combination of: commas, semicolons, colons, pipes, spaces,
        # newlines or tabs — any mix of these, in any amount, counts as a separator.
        raw_text = st.session_state.group_email_input.strip()
        if not raw_text:
            st.warning(f"Please paste at least one {idm_input_type.lower()}.")

        # ══════════════════════════════════════════════════════════════════
        # NAME INPUT — fuzzy/tiered matching engine
        # ══════════════════════════════════════════════════════════════════
        elif idm_input_type == "Name":
            raw_lines = [l for l in raw_text.split("\n") if l.strip()]
            entries = []  # list of (display_text, entry_for_scoring)
            if idm_paste_format == "two_col":
                for line in raw_lines:
                    parts = line.split("\t") if "\t" in line else line.split(",", 1)
                    first = parts[0].strip() if len(parts) > 0 else ""
                    surname = parts[1].strip() if len(parts) > 1 else ""
                    entries.append((f"{first} {surname}".strip(), (first, surname)))
            else:
                for line in raw_lines:
                    name = line.strip()
                    entries.append((name, name))

            if not entries:
                st.error("No names found. Please check your input.")
            else:
                df_gc = None
                if gc_csv is not None:
                    try:
                        gc_csv.seek(0)
                        df_gc = pd.read_csv(gc_csv).fillna("")
                    except Exception as e:
                        st.error(f"Could not read uploaded CSV: {e}")
                elif "df_final" in st.session_state:
                    df_gc = st.session_state.df_final

                if df_gc is None:
                    st.warning("Please upload a Student List CSV (or load one via the Booklet Creator tab first).")
                else:
                    roster, email_col_nm = _idm_build_roster(df_gc)
                    no_email_col = email_col_nm is None and idm_output_type == "Email"

                    auto_matched = []   # (display, row_dict)
                    review_items = []   # {key, display, candidates:[(row_dict,score)...], suggested_id}

                    for i, (display, entry) in enumerate(entries):
                        candidates = _idm_score_entry(entry, idm_paste_format, roster)
                        auto_row, suggested_row = _idm_classify_entry(candidates)
                        if auto_row is not None:
                            auto_matched.append((display, auto_row))
                        else:
                            review_items.append({
                                "key": f"nm_{i}",
                                "display": display,
                                "candidates": candidates,
                                "suggested_id": suggested_row["id"] if suggested_row else None,
                            })

                    matched_ids = {row["id"] for _, row in auto_matched}
                    csv_unmatched = [
                        (rd["id"], f"{rd['fname']} {rd['surname']}".strip())
                        for rd in roster if rd["id"] not in matched_ids
                    ]

                    st.session_state.idm_name_manual_selections = {}
                    st.session_state.group_results = {
                        "matched_rows": auto_matched,
                        "review_items": review_items,
                        "csv_unmatched": csv_unmatched,
                        "invalid_tokens": [],
                        "no_email_col": no_email_col,
                        "email_col_used": email_col_nm,
                        "input_type": idm_input_type,
                        "output_type": idm_output_type,
                        "is_name_input": True,
                    }
                    st.rerun()

        # ══════════════════════════════════════════════════════════════════
        # STUDENT ID / EMAIL INPUT — exact-match lookup (unchanged)
        # ══════════════════════════════════════════════════════════════════
        else:
            # Split on any combination of: commas, semicolons, colons, pipes, spaces,
            # newlines or tabs — any mix of these, in any amount, counts as a separator.
            tokens_raw = [t for t in re.split(r'[\s,;:|]+', raw_text) if t]

            if idm_input_type == "Email":
                email_pattern = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
                input_values = [t.strip().lower() for t in tokens_raw if email_pattern.match(t.strip())]
                invalid = [t.strip() for t in tokens_raw if not email_pattern.match(t.strip())]
            else:  # Student ID — no strict format, just de-blank and de-space
                input_values = [t.strip() for t in tokens_raw]
                invalid = []

            if not input_values:
                st.error(f"No valid {idm_input_type.lower()}s found. Please check your input.")
            else:
                # ── Load student data ─────────────────────────────────────────
                df_gc = None

                if gc_csv is not None:
                    try:
                        gc_csv.seek(0)
                        df_gc = pd.read_csv(gc_csv).fillna("")
                    except Exception as e:
                        st.error(f"Could not read uploaded CSV: {e}")

                elif "df_final" in st.session_state:
                    df_gc = st.session_state.df_final

                if df_gc is None:
                    st.warning("Please upload a Student List CSV (or load one via the Booklet Creator tab first).")
                else:
                    # ── Locate the email column (auto-detected — not in config.yaml) ──
                    email_col = None
                    for candidate in ["Email", "email", "Email address", "Email Address",
                                      "Student email", "Student Email", "EmailAddress"]:
                        if candidate in df_gc.columns:
                            email_col = candidate
                            break
                    if email_col is None:
                        for col in df_gc.columns:
                            if "email" in col.lower():
                                email_col = col
                                break

                    id_col    = COLS.get('student_id', 'Code')
                    fname_col = COLS.get('first_name', 'First name')
                    pref_col  = COLS.get('preferred_name', 'Preferred name')
                    sname_col = COLS.get('surname', 'Surname')
                    no_email_col = email_col is None and (idm_input_type == "Email" or idm_output_type == "Email")

                    matched_rows = []      # (input_value, row_dict) — row_dict has id/email/fname/pref/surname
                    unmatched_inputs = []
                    csv_unmatched = []     # (display_key, name) — CSV rows never hit by the pasted list

                    if no_email_col:
                        unmatched_inputs = input_values
                    else:
                        # key_col = column holding what the user pasted in.
                        key_col = email_col if idm_input_type == "Email" else id_col
                        normalise = (lambda v: str(v).strip().lower()) if idm_input_type == "Email" else (lambda v: str(v).strip())

                        lookup = {}
                        for _, row in df_gc.iterrows():
                            raw_key = str(row.get(key_col, "")).strip()
                            key = raw_key.lower() if idm_input_type == "Email" else raw_key
                            if key and key != 'nan':
                                row_dict = {
                                    "id": str(row.get(id_col, "")).strip(),
                                    "email": str(row.get(email_col, "")).strip() if email_col else "",
                                    "fname": str(row.get(fname_col, "")).strip(),
                                    "pref": str(row.get(pref_col, "")).strip(),
                                    "surname": str(row.get(sname_col, "")).strip(),
                                }
                                full_name = f"{row_dict['fname']} {row_dict['surname']}".strip()
                                # Later rows with a duplicate key simply overwrite —
                                # matches existing single-lookup behaviour.
                                lookup[key] = (row_dict, full_name, raw_key)

                        matched_keys_used = set()
                        for val in input_values:
                            key = normalise(val)
                            if key in lookup:
                                row_dict, name, _ = lookup[key]
                                matched_rows.append((val, row_dict))
                                matched_keys_used.add(key)
                            else:
                                unmatched_inputs.append(val)

                        csv_unmatched = [
                            (display_key, name)
                            for key, (row_dict, name, display_key) in lookup.items()
                            if key not in matched_keys_used
                        ]

                    # ── Store results ─────────────────────────────────────────
                    # Output values aren't baked in here — they're computed at display
                    # time from matched_rows, so switching the Name output format
                    # afterwards updates the results instantly without re-matching.
                    st.session_state.group_results = {
                        "matched_rows": matched_rows,
                        "unmatched_inputs": unmatched_inputs,
                        "csv_unmatched": csv_unmatched,
                        "invalid_tokens": invalid,
                        "no_email_col": no_email_col,
                        "email_col_used": email_col,
                        "input_type": idm_input_type,
                        "output_type": idm_output_type,
                        "is_name_input": False,
                    }
                    st.rerun()



    # ── Display results — Name input (tiered auto-match + manual review) ──────
    if st.session_state.group_results and st.session_state.group_results.get("is_name_input"):
        res = st.session_state.group_results
        auto_rows       = res["matched_rows"]     # (display, row_dict) — confidently auto-matched
        review_items    = res["review_items"]     # need a human decision
        csv_unmatched0  = res["csv_unmatched"]
        no_email_col    = res["no_email_col"]
        res_output_type = res["output_type"]

        def _idm_output_value_nm(row_dict):
            if res_output_type == "Student ID":
                return row_dict["id"]
            elif res_output_type == "Email":
                return row_dict["email"]
            return ""

        st.markdown("---")

        if no_email_col:
            st.error(
                "⚠️ No email column was found in the student CSV. "
                "The CSV needs a column with 'email' in the name (e.g. 'Email', 'Email address'). "
                "Check your export settings in SEQTA."
            )
        else:
            n_auto, n_review = len(auto_rows), len(review_items)
            st.markdown(
                f'<div class="group-output-label">🔎 {n_auto} matched automatically'
                f'{f" · {n_review} need review" if n_review else ""}</div>',
                unsafe_allow_html=True
            )

            manual_confirmed = []  # (display, row_dict) — from the dropdowns below
            if review_items:
                with st.expander(
                    f"⚠️  {n_review} name{'s' if n_review != 1 else ''} need manual matching — "
                    f"closest matches are pre-sorted",
                    expanded=True
                ):
                    st.caption(
                        "Typos, nicknames, and students who share a name can't always be resolved "
                        "automatically. Pick the right student for each row below, or leave it as Skip."
                    )
                    for item in review_items:
                        rc1, rc2 = st.columns([2, 3])
                        with rc1:
                            st.markdown(f"**{item['display']}**")
                            if not item["candidates"]:
                                st.caption("No similar names found in the student list.")
                        with rc2:
                            options = ["(Skip)"]
                            option_map = {}
                            default_idx = 0
                            for row_dict, score in item["candidates"]:
                                label = f"{row_dict['fname']} {row_dict['surname']}"
                                if row_dict['pref'] and row_dict['pref'].lower() != row_dict['fname'].lower():
                                    label += f" ({row_dict['pref']})"
                                label += f" — ID {row_dict['id']}"
                                if row_dict.get('year'):
                                    label += f", Year {row_dict['year']}"
                                if row_dict.get('roll'):
                                    label += f", {row_dict['roll']}"
                                label += f"  [{round(score * 100)}% match]"
                                options.append(label)
                                option_map[label] = row_dict
                                if row_dict["id"] == item.get("suggested_id") and default_idx == 0:
                                    default_idx = len(options) - 1
                            sel = st.selectbox(
                                "Assign to student:", options=options, index=default_idx,
                                key=f"idm_name_review_{item['key']}", label_visibility="collapsed"
                            )
                            if sel != "(Skip)":
                                st.session_state.idm_name_manual_selections[item['key']] = option_map[sel]
                                manual_confirmed.append((item['display'], option_map[sel]))
                            elif item['key'] in st.session_state.idm_name_manual_selections:
                                del st.session_state.idm_name_manual_selections[item['key']]
                        st.divider()
            elif n_auto:
                st.success(f"✅ All {n_auto} names matched automatically")

            all_matched = auto_rows + manual_confirmed
            matched_values = [_idm_output_value_nm(rd) for _, rd in all_matched]
            matched_details = [
                (disp, _idm_output_value_nm(rd), f"{rd['fname']} {rd['surname']}".strip())
                for disp, rd in all_matched
            ]
            matched_ids_final = {rd["id"] for _, rd in all_matched}
            csv_unmatched = [(sid_, name_) for (sid_, name_) in csv_unmatched0 if sid_ not in matched_ids_final]

            result_col1, result_col2 = st.columns([3, 2])
            with result_col1:
                if matched_values:
                    is_id_output = (res_output_type == "Student ID")
                    label_noun = "student code" if is_id_output else res_output_type.lower()
                    st.markdown(
                        f'<div class="group-output-label">✅ {len(matched_values)} {label_noun}'
                        f'{"s" if len(matched_values) != 1 else ""} ready'
                        f'{" — copy and paste into SEQTA" if is_id_output else ""}</div>',
                        unsafe_allow_html=True
                    )
                    output_text = "\n".join(matched_values)
                    st.text_area(
                        "Matched output values", value=output_text,
                        height=max(120, min(400, len(matched_values) * 26)),
                        label_visibility="collapsed", key="gc_output_box_name"
                    )
                    if is_id_output:
                        st.markdown("""
                        <div class="seqta-instruction">
                          <strong>📌 Next step:</strong> In SEQTA, open your
                          <a href="https://teach.friends.tas.edu.au/students/classes" target="_blank" style="color:#7a5a00;font-weight:600">custom group editor</a>,
                          paste these codes one per line into the box on the left, then click <strong>OK</strong>.
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("No matches confirmed yet — resolve the items above.")

            with result_col2:
                if matched_details:
                    with st.expander(f"✅ {len(matched_details)} confirmed", expanded=False):
                        for in_val, out_val, name in matched_details:
                            st.markdown(
                                f"<span style='font-size:0.8rem'><b>{out_val}</b> — {name}"
                                f"<br><span style='color:#9295a8'>{in_val}</span></span>",
                                unsafe_allow_html=True
                            )
                if csv_unmatched:
                    with st.expander(f"ℹ️ {len(csv_unmatched)} student(s) in the CSV not referenced", expanded=False):
                        st.caption(
                            "These students from the student list weren't matched (automatically or "
                            "manually) to any of the names you pasted in."
                        )
                        for sid_, name_ in csv_unmatched:
                            st.markdown(
                                f"<span style='font-size:0.8rem;color:#9295a8'>{name_} — {sid_}</span>",
                                unsafe_allow_html=True
                            )

        if st.button("↩  Clear results", key="gc_clear_btn_name"):
            st.session_state.group_results = None
            st.session_state.group_email_input = ""
            st.session_state.idm_name_manual_selections = {}
            st.rerun()

    # ── Display results — Student ID / Email input (exact match) ──────────────
    elif st.session_state.group_results:
        res = st.session_state.group_results
        matched_rows      = res["matched_rows"]      # (input_value, row_dict)
        unmatched_inputs  = res["unmatched_inputs"]
        invalid_tokens    = res["invalid_tokens"]
        no_email_col      = res["no_email_col"]
        res_input_type    = res["input_type"]
        res_output_type   = res["output_type"]

        # Output values are computed here (not at match time) so switching the
        # Name output format afterwards updates results instantly, no re-run needed.
        def _idm_output_value(row_dict):
            if res_output_type == "Student ID":
                return row_dict["id"]
            elif res_output_type == "Email":
                return row_dict["email"]
            elif res_output_type == "Name":
                return _idm_format_name(row_dict["fname"], row_dict["pref"], row_dict["surname"], st.session_state.idm_name_format)
            return ""

        matched_values = [_idm_output_value(row_dict) for _, row_dict in matched_rows]
        matched_details = [
            (in_val, _idm_output_value(row_dict), f"{row_dict['fname']} {row_dict['surname']}".strip())
            for in_val, row_dict in matched_rows
        ]

        st.markdown("---")

        if no_email_col:
            st.error(
                "⚠️ No email column was found in the student CSV. "
                "The CSV needs a column with 'email' in the name (e.g. 'Email', 'Email address'). "
                "Check your export settings in SEQTA."
            )
        else:
            result_col1, result_col2 = st.columns([3, 2])

            with result_col1:
                if matched_values:
                    is_id_output = (res_output_type == "Student ID")
                    label_noun = "student code" if is_id_output else res_output_type.lower()
                    st.markdown(f'<div class="group-output-label">✅ {len(matched_values)} {label_noun}{"s" if len(matched_values) != 1 else ""} found{" — copy and paste into SEQTA" if is_id_output else ""}</div>', unsafe_allow_html=True)
                    output_text = "\n".join(matched_values)
                    st.text_area(
                        "Matched output values",
                        value=output_text,
                        height=max(120, min(400, len(matched_values) * 26)),
                        label_visibility="collapsed",
                        key="gc_output_box"
                    )
                    if is_id_output:
                        st.markdown("""
                        <div class="seqta-instruction">
                          <strong>📌 Next step:</strong> In SEQTA, open your
                          <a href="https://teach.friends.tas.edu.au/students/classes" target="_blank" style="color:#7a5a00;font-weight:600">custom group editor</a>,
                          paste these codes one per line into the box on the left, then click <strong>OK</strong>.
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info(f"No {res_output_type.lower()}s were matched. Check the {res_input_type.lower()}s and CSV below.")

            with result_col2:
                if matched_details:
                    with st.expander(f"✅ {len(matched_details)} matched", expanded=False):
                        for in_val, out_val, name in matched_details:
                            # When the output IS the name, skip the redundant " — name" suffix.
                            detail_line = f"<b>{out_val}</b>" if res_output_type == "Name" else f"<b>{out_val}</b> — {name}"
                            st.markdown(f"<span style='font-size:0.8rem'>{detail_line}<br><span style='color:#9295a8'>{in_val}</span></span>", unsafe_allow_html=True)

                if unmatched_inputs or res["csv_unmatched"]:
                    nm_view = st.radio(
                        "Show unmatched from",
                        options=[f"My {res_input_type.lower()} list", "Student list CSV"],
                        horizontal=True,
                        key="gc_nm_view"
                    )

                    if nm_view.startswith("My"):
                        if unmatched_inputs:
                            with st.expander(f"❌ {len(unmatched_inputs)} {res_input_type.lower()}{'s' if len(unmatched_inputs) != 1 else ''} not matched", expanded=True):
                                st.caption(f"These {res_input_type.lower()}s you pasted in weren't found in the student list CSV.")
                                for val in unmatched_inputs:
                                    st.markdown(f"<span style='font-size:0.8rem;color:#c0392b'>{val}</span>", unsafe_allow_html=True)
                        else:
                            st.caption(f"Every {res_input_type.lower()} you pasted in was matched. ✅")
                    else:
                        csv_unmatched = res["csv_unmatched"]
                        if csv_unmatched:
                            with st.expander(f"❌ {len(csv_unmatched)} student{'s' if len(csv_unmatched) != 1 else ''} in the CSV not matched", expanded=True):
                                st.caption(f"These students from the student list CSV weren't found in the {res_input_type.lower()}s you pasted in.")
                                for display_key, name in csv_unmatched:
                                    st.markdown(f"<span style='font-size:0.8rem;color:#c0392b'>{name} <span style='color:#9295a8'>— {display_key}</span></span>", unsafe_allow_html=True)
                        else:
                            st.caption("Every student in the CSV was matched. ✅")

                if invalid_tokens:
                    with st.expander(f"⚠️ {len(invalid_tokens)} invalid token{'s' if len(invalid_tokens) != 1 else ''} skipped"):
                        st.caption(f"These entries didn't look like {res_input_type.lower()}s and were ignored.")
                        for tok in invalid_tokens:
                            st.markdown(f"<span style='font-size:0.8rem;color:#9295a8'>{tok}</span>", unsafe_allow_html=True)

        if st.button("↩  Clear results", key="gc_clear_btn"):
            st.session_state.group_results = None
            st.session_state.group_email_input = ""
            st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — ATTACHMENT DOWNLOADER
# Student List CSV only -> download every action plan from the portal -> save as a folder (ZIP).
# Uses the same download / clean-up / naming functions as Step 3 of the Booklet Creator.
# ═══════════════════════════════════════════════════════════════════════════════
if t4 is not None:
 with t4:

    st.markdown('<div class="section-head">Attachment Downloader</div>', unsafe_allow_html=True)
    st.markdown(
        "Download every student's medical action plan from the portal in one go and save them as a folder, "
        "each file named with the student's ID and name. All you need is the Student List CSV. "
        "The saved folder can be dropped into the Medical Booklet Creator later (Step 3 → Advanced Options → Import saved plans)."
    )

    # ── Step 1: Student List CSV ──────────────────────────────────────────────
    st.markdown('<div class="section-head">Step 1 — Student List CSV</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="upload-card">
      <div class="upload-card-label">Student List CSV</div>
      <div class="upload-card-desc">Student data from Seqta — the action plan links are read from the medical notes.
      <br><a class="seqta-link" href="{SEQTA_URL}" target="_blank" style="margin-top:6px;display:inline-flex">↗ Open in Seqta</a></div>
    </div>
    """, unsafe_allow_html=True)
    att_csv = st.file_uploader("Student List CSV for attachment downloader", type="csv",
                               label_visibility="collapsed", key="att_csv_uploader")

    att_df = None
    if att_csv is not None:
        try:
            att_df = pd.read_csv(att_csv, dtype=str).fillna("")
        except Exception as _e:
            st.error(f"Could not read that CSV: {_e}")
    elif "df_final" in st.session_state:
        att_df = st.session_state.df_final
        st.caption("💡 A student list is already loaded from the Booklet Creator — it will be used if no file is uploaded here.")

    if att_df is not None:
        _need = [COLS['student_id'], COLS['surname'], COLS['first_name'], COLS['medical_notes']]
        _missing = [c for c in _need if c not in att_df.columns]
        if _missing:
            st.error("This CSV is missing the expected column(s): " + ", ".join(f"'{c}'" for c in _missing)
                     + ". Make sure it's the Student List export from Seqta.")
            att_df = None

    if att_df is None:
        st.info("Upload the Student List CSV to get started.")
    else:
        att_detected = detect_medical_plans(att_df)
        _att_id_to_sf   = {str(r[COLS['student_id']]): (r[COLS['surname']], r[COLS['first_name']])
                           for _, r in att_df.iterrows()}
        _att_id_to_name = {s: f"{f} {sn}" for s, (sn, f) in _att_id_to_sf.items()}

        # Flat task list, in student-name order. Plan numbers match the Booklet Creator's slots.
        att_tasks = []
        for _sid in sorted(att_detected, key=lambda s: (_att_id_to_sf.get(s, ("", ""))[0].lower(),
                                                         _att_id_to_sf.get(s, ("", ""))[1].lower())):
            for _i, _pl in enumerate(att_detected[_sid]):
                att_tasks.append({"key": f"{_sid}_{_i}", "sid": _sid, "idx": _i,
                                  "condition": _pl.get("condition") or "Action plan",
                                  "url": _pl.get("url"), "name": _att_id_to_name.get(_sid, _sid)})
        _task_by_key = {t["key"]: t for t in att_tasks}

        for _k, _d in (("att_files", {}), ("att_errors", {}), ("att_manual", {})):
            if _k not in st.session_state:
                st.session_state[_k] = _d

        if not att_tasks:
            st.warning("No action plans were found in this student list's medical notes.")
        else:
            _n_students = len({t["sid"] for t in att_tasks})
            st.success(f"✅ {len(att_tasks)} action plan(s) found for {_n_students} student(s) "
                       f"out of {len(att_df)} in the list.")

            # ── Step 2: portal session ─────────────────────────────────────────
            st.markdown('<div class="section-head">Step 2 — Portal session</div>', unsafe_allow_html=True)
            _host = CONFIG['app_settings'].get('school_portal_url', '')
            _domain = _host.replace("https://", "").replace("http://", "").split("/")[0]
            with st.expander("How to get your session cookie"):
                st.markdown(f"""
1. Log into [{_domain}]({_host}) in Chrome or Safari as normal
2. Press **F12** to open DevTools (or right-click anywhere → **Inspect**)
3. Click the **Application** tab (Chrome) or **Storage** tab (Safari)
4. In the left panel: **Cookies** → click `{_domain}`
5. Find the cookie named **`ASP.NET_SessionId`** (or `SEQTASESSION`)
6. Click it and copy the **Value** column
7. Paste it below
""")
                st.info("💡 The cookie expires when you log out of the portal. If downloads fail, log back in and copy a fresh value. "
                        "Your credentials are never stored — only the temporary session value is used.", icon="ℹ️")
            _cc1, _cc2 = st.columns([3, 1])
            with _cc1:
                att_cookie = st.text_input("Session cookie value", value=st.session_state.get("_portal_cookie", ""),
                                           type="password", placeholder="Paste cookie value here…",
                                           key="att_cookie_input")
            with _cc2:
                att_cookie_name = st.text_input("Cookie name", value=st.session_state.get("_portal_cookie_name", "ASP.NET_SessionId"),
                                                key="att_cookie_name_input") or "ASP.NET_SessionId"
            if att_cookie:
                st.session_state["_portal_cookie"] = att_cookie
                st.session_state["_portal_cookie_name"] = att_cookie_name

            # ── Step 3: download ───────────────────────────────────────────────
            st.markdown('<div class="section-head">Step 3 — Download</div>', unsafe_allow_html=True)

            def _att_run(tasks):
                """Download the given tasks (4 at a time), recording files and per-plan errors."""
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _fetch(t):
                    fobj, fname, err = auto_download_plan(t["url"], att_cookie, cookie_name=att_cookie_name)
                    return t["key"], (fobj.getvalue() if fobj else None), fname, err

                todo = []
                for t in tasks:
                    if not t["url"]:
                        st.session_state.att_errors[t["key"]] = "No download link in the student data"
                    else:
                        todo.append(t)
                if not todo:
                    return True

                # Probe one first: an expired/incorrect cookie would fail everything, so stop early.
                bar = st.progress(0, text="Checking your portal session…")
                k0, b0, f0, e0 = _fetch(todo[0])
                if b0 is None and e0 and ("cookie" in e0.lower() or "login" in e0.lower()):
                    bar.empty()
                    st.error(f"❌ {e0} Log back into the portal, copy a fresh cookie value above, and try again.")
                    return False
                results = [(k0, b0, f0, e0)]
                done = 1
                bar.progress(done / len(todo), text=f"Downloading… {done} of {len(todo)}")
                with ThreadPoolExecutor(max_workers=4) as ex:
                    futs = [ex.submit(_fetch, t) for t in todo[1:]]
                    for fu in as_completed(futs):
                        results.append(fu.result())
                        done += 1
                        bar.progress(done / len(todo), text=f"Downloading… {done} of {len(todo)}")
                bar.empty()
                for k, data, fname, err in results:
                    if data:
                        st.session_state.att_files[k] = (data, fname)
                        st.session_state.att_errors.pop(k, None)
                    else:
                        st.session_state.att_errors[k] = err or "Unknown error"
                st.session_state.pop("att_zip_cache", None)
                return True

            def _att_have(k):
                return k in st.session_state.att_manual or k in st.session_state.att_files

            _pending = [t for t in att_tasks if not _att_have(t["key"])]
            _retry   = [t for t in att_tasks if t["key"] in st.session_state.att_errors and not _att_have(t["key"])]
            _b1, _b2, _b3 = st.columns([2, 2, 1])
            with _b1:
                if not att_cookie:
                    st.button(f"⬇ Download all {len(att_tasks)} plan(s)", disabled=True,
                              help="Paste your session cookie above first", key="att_dl_all_disabled")
                elif st.button(f"⬇ Download all {len(att_tasks)} plan(s)", type="primary", key="att_dl_all"):
                    st.session_state.att_errors = {}
                    if _att_run([t for t in att_tasks if not st.session_state.att_manual.get(t["key"])]):
                        st.session_state.att_ran = True
                        st.rerun()
            with _b2:
                if att_cookie and _retry and st.button(f"🔄 Retry {len(_retry)} failed", key="att_retry"):
                    if _att_run(_retry):
                        st.rerun()
            with _b3:
                if st.button("↩ Clear", key="att_clear"):
                    for _k in ("att_files", "att_errors", "att_manual", "att_ran", "att_zip_cache"):
                        st.session_state.pop(_k, None)
                    st.rerun()

            # ── Results ────────────────────────────────────────────────────────
            if st.session_state.get("att_ran"):
                _held = []
                for t in att_tasks:
                    src = st.session_state.att_manual.get(t["key"]) or st.session_state.att_files.get(t["key"])
                    if src and src[0]:
                        _held.append((t["sid"], t["idx"] + 1, t["condition"], src[0], src[1]))
                _failed = [t for t in att_tasks if not (st.session_state.att_manual.get(t["key"])
                                                         or st.session_state.att_files.get(t["key"]))]

                st.markdown('<div class="section-head">Results</div>', unsafe_allow_html=True)
                if _held:
                    st.success(f"✅ {len(_held)} of {len(att_tasks)} plan(s) ready")
                if _failed:
                    st.warning(f"⚠️ {len(_failed)} plan(s) could not be downloaded")

                # Folder (ZIP) — cached so it isn't rebuilt on every click
                if _held:
                    _sig = (tuple((h[0], h[1], len(h[3])) for h in _held))
                    _cache = st.session_state.get("att_zip_cache")
                    if not _cache or _cache["sig"] != _sig:
                        with st.spinner("Preparing folder…"):
                            _zb, _zp, _zr = build_plans_zip(_held, _att_id_to_sf)
                        _cache = {"sig": _sig, "zip": _zb, "problems": _zp, "repaired": _zr}
                        st.session_state.att_zip_cache = _cache
                    if _cache["repaired"]:
                        st.caption(f"🔧 {len(_cache['repaired'])} file(s) were cleaned up so they open normally.")
                    if _cache["problems"]:
                        st.warning("These file(s) couldn't be turned into a PDF and may not open — "
                                   "download them manually instead:\n\n"
                                   + "\n".join(f"- `{n}` — {why}" for n, why in _cache["problems"][:25]))
                    st.download_button(
                        f"⬇ Download {len(_held)} action plan(s) (ZIP folder)",
                        data=_cache["zip"],
                        file_name=f"{PLAN_FOLDER_NAME}_{datetime.now().strftime('%Y-%m-%d')}.zip",
                        mime="application/zip", type="primary", key="att_zip_dl",
                    )
                    st.caption(f"Each file is named like `12345__Smith_Jane__01_Anaphylaxis.pdf` (student ID, name, plan number, condition).")

                # Failures: reason + manual link + optional upload so the folder can still be completed
                if _failed:
                    st.markdown("**Plans that need downloading manually**")
                    st.caption("Open each link (you'll need to be logged into the portal), save the file, then upload it here "
                               "and it will be added to the folder with the correct name.")
                    for t in _failed:
                        _c1, _c2 = st.columns([3, 2])
                        with _c1:
                            st.markdown(f"**{t['name']}** — {t['condition']}")
                            st.caption(f"❌ {st.session_state.att_errors.get(t['key'], 'Not downloaded yet')}")
                            if t["url"]:
                                st.markdown(f"[↗ Open / download manually]({t['url']})")
                        with _c2:
                            _up = st.file_uploader(f"Add file for {t['name']} — {t['condition']}",
                                                   type=['pdf', 'png', 'jpg', 'jpeg'],
                                                   key=f"att_man_{t['key']}", label_visibility="collapsed")
                            if _up is not None:
                                _raw = _up.getvalue()
                                if _raw and st.session_state.att_manual.get(t["key"], (None, None))[1] != _up.name:
                                    st.session_state.att_manual[t["key"]] = (_raw, _up.name)
                                    st.session_state.pop("att_zip_cache", None)
                                    st.rerun()
                        st.divider()
                elif _held:
                    st.success("🎉 Every action plan was downloaded.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="mbc-footer">
  Medical Booklet Tools &nbsp;·&nbsp; Created by Thomas van Sant
</div>
""", unsafe_allow_html=True)
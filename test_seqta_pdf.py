#!/usr/bin/env python3
"""
test_seqta_pdf.py — Standalone tester for Seqta Contact PDF parser
─────────────────────────────────────────────────────────────────────
Run from Terminal inside your medical-booklet folder:

    python test_seqta_pdf.py  <contact_pdf>  <student_csv>

Example:
    python test_seqta_pdf.py  "Excursion contact info.pdf"  "students.csv"

This script is SAFE to run — it only reads files, never writes anything.
It prints a full diagnostic report so you can verify what is being
extracted before it touches your main app.
"""

import sys
import os
import re
import pdfplumber
import pandas as pd
import yaml


# ─────────────────────────────────────────────────────────────────────────────
# PDF PARSER
# ─────────────────────────────────────────────────────────────────────────────

def parse_contacts_cell(text):
    """
    Parses the 'Contacts' column text for one student.

    Expected layout (any lines may be absent):
        123 Smith Street HOBART TAS 7050
        Home: 03 6221 0000  Mobile: 0400 000 000
        Mother Jane Smith
          Mobile: 0400 111 111
          Home: 03 6221 0001  Work: 03 6221 0002
        Father Bob Smith
          Mobile: 0400 222 222
          Home:   Work:
        [additional guardian blocks follow the same pattern]

    Returns a dict:
        {
          "home_address": str,
          "home_phone":   str,
          "home_mobile":  str,
          "guardians": [
              {
                "relationship": str,   # "Mother", "Father", or raw label
                "name":         str,
                "mobile":       str,
                "home":         str,
                "work":         str,
              },
              ...
          ]
        }
    """
    result = {
        "home_address": "",
        "home_phone":   "",
        "home_mobile":  "",
        "guardians":    [],
    }

    if not text or not text.strip():
        return result

    lines = [l.strip() for l in text.strip().splitlines()]

    # ── Detect which lines are "Home: … Mobile: …" phone lines ───────────────
    phone_line_re = re.compile(
        r'(?:Home:\s*([\d\s]+)?)?(?:\s*Mobile:\s*([\d\s]+)?)?', re.IGNORECASE
    )
    guardian_start_re = re.compile(
        r'^(Mother|Father|Guardian|Parent|Step\s*\w*|Carer|Uncle|Aunt|'
        r'Grandm\w*|Grandf\w*|Step\w*|Relation\w*|Emergency\w*|Other\w*)\b',
        re.IGNORECASE
    )

    i = 0
    address_found = False
    home_phone_found = False

    while i < len(lines):
        line = lines[i]

        if not line:
            i += 1
            continue

        # ── Guardian / relationship block ──────────────────────────────────
        guardian_match = guardian_start_re.match(line)
        if guardian_match:
            relationship = guardian_match.group(1).strip().title()
            # Everything after the relationship label is the name
            raw_name = line[guardian_match.end():].strip()
            # Clean up any stray punctuation
            name = re.sub(r'^[:\-–\s]+', '', raw_name).strip()

            guardian = {
                "relationship": relationship,
                "name":         name,
                "mobile":       "",
                "home":         "",
                "work":         "",
            }

            # Consume the next lines that belong to this guardian (phone details)
            i += 1
            while i < len(lines):
                sub = lines[i]
                if not sub:
                    i += 1
                    break

                # Stop if the next line is another guardian
                if guardian_start_re.match(sub):
                    break

                # Mobile:
                m = re.search(r'Mobile:\s*([\d\s\+\(\)]+)', sub, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val:
                        guardian["mobile"] = val

                # Home:
                m = re.search(r'Home:\s*([\d\s\+\(\)]+)', sub, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val:
                        guardian["home"] = val

                # Work:
                m = re.search(r'Work:\s*([\d\s\+\(\)]+)', sub, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val:
                        guardian["work"] = val

                i += 1

            result["guardians"].append(guardian)
            continue

        # ── Student home phone line ("Home: … Mobile: …") ─────────────────
        if not home_phone_found and re.search(r'Home:', line, re.IGNORECASE):
            hm = re.search(r'Home:\s*([\d\s\+\(\)]*)', line, re.IGNORECASE)
            mm = re.search(r'Mobile:\s*([\d\s\+\(\)]+)', line, re.IGNORECASE)
            if hm:
                result["home_phone"]  = hm.group(1).strip()
            if mm:
                result["home_mobile"] = mm.group(1).strip()
            home_phone_found = True
            i += 1
            continue

        # ── First non-empty, non-phone line → home address ─────────────────
        if not address_found:
            result["home_address"] = line
            address_found = True
            i += 1
            continue

        i += 1

    return result


def parse_student_cell(text):
    """
    Parses the 'Student' column text for one student.

    Seqta format (typical):
        Smith John (Johnny)
        <house>  <year>  <rollgroup>

    Returns:
        {
          "surname":    str,
          "first_name": str,   # legal first name
          "preferred":  str,   # preferred name (from brackets), may equal first_name
          "year":       str,
          "rollgroup":  str,
          "house":      str,
        }
    """
    result = {
        "surname":   "",
        "first_name": "",
        "preferred":  "",
        "year":       "",
        "rollgroup":  "",
        "house":      "",
    }

    if not text or not text.strip():
        return result

    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    if not lines:
        return result

    # ── Line 1: name ──────────────────────────────────────────────────────
    name_line = lines[0]

    # Extract preferred name from brackets e.g. "(Johnny)"
    pref_match = re.search(r'\(([^)]+)\)', name_line)
    preferred = pref_match.group(1).strip() if pref_match else ""
    name_clean = re.sub(r'\([^)]*\)', '', name_line).strip()

    parts = name_clean.split()
    if len(parts) >= 2:
        result["surname"]    = parts[0]
        result["first_name"] = parts[1]
    elif len(parts) == 1:
        result["surname"] = parts[0]

    result["preferred"] = preferred if preferred else result["first_name"]

    # ── Line 2: class details ─────────────────────────────────────────────
    if len(lines) >= 2:
        class_line = lines[1]
        # Three whitespace-separated tokens: house  year  rollgroup
        tokens = class_line.split()
        if len(tokens) >= 3:
            result["house"]     = tokens[0]
            result["year"]      = tokens[1]
            result["rollgroup"] = tokens[2]
        elif len(tokens) == 2:
            result["year"]      = tokens[0]
            result["rollgroup"] = tokens[1]

    return result


def parse_seqta_contact_pdf(pdf_path_or_buffer):
    """
    Main parser.  Accepts either a file path string or a file-like object.

    Returns a list of dicts, one per student found in the PDF:
        {
          "surname", "first_name", "preferred", "year", "rollgroup", "house",
          "dob",
          "home_address", "home_phone", "home_mobile",
          "guardians": [ { "relationship", "name", "mobile", "home", "work" } ]
        }
    """
    records = []

    open_args = {}
    if isinstance(pdf_path_or_buffer, str):
        open_kwargs = {"path": pdf_path_or_buffer}
    else:
        open_kwargs = {"file_obj": pdf_path_or_buffer}
        if hasattr(pdf_path_or_buffer, "seek"):
            pdf_path_or_buffer.seek(0)

    with pdfplumber.open(**open_kwargs) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            # Use pdfplumber's table extractor with loose settings so that
            # multi-line cells are kept together
            tables = page.extract_tables({
                "vertical_strategy":   "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance":      5,
                "join_tolerance":      3,
            })

            if not tables:
                # Fallback: try text-based strategy
                tables = page.extract_tables({
                    "vertical_strategy":   "text",
                    "horizontal_strategy": "lines",
                })

            for table in tables:
                for row_idx, row in enumerate(table):
                    if not row:
                        continue

                    # Skip header rows
                    first_cell = (row[0] or "").strip().lower()
                    if first_cell in ("student", "name", ""):
                        continue

                    # We expect at least 3 columns: student | dob | contacts
                    if len(row) < 3:
                        continue

                    student_text   = row[0] or ""
                    dob_text       = (row[1] or "").strip()
                    contacts_text  = row[2] or ""
                    # row[3] = medical — intentionally ignored

                    student_info  = parse_student_cell(student_text)
                    contacts_info = parse_contacts_cell(contacts_text)

                    if not student_info["surname"]:
                        continue   # Skip empty rows

                    record = {
                        **student_info,
                        "dob":          dob_text,
                        **contacts_info,
                        "_page":        page_num,
                        "_row":         row_idx,
                    }
                    records.append(record)

    return records


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT MATCHING
# ─────────────────────────────────────────────────────────────────────────────

def match_to_student_list(pdf_records, df_students, config):
    """
    Attempts to match each PDF record to a student in the student list CSV.

    Matching strategy (in order):
      1. Exact surname + first_name  (case-insensitive)
      2. Exact surname + preferred   (case-insensitive)
      3. Surname-only                (only used when surname is unique in CSV)

    Returns:
        matched   : { student_id: pdf_record_dict }
        unmatched : [ pdf_record_dict ]
        ambiguous : [ (pdf_record_dict, [candidate_ids]) ]
    """
    cols = config.get("column_mappings", {})
    id_col   = cols.get("student_id", "Code")
    fn_col   = cols.get("first_name",  "First name")
    sn_col   = cols.get("surname",     "Surname")

    # Build lookups from student CSV
    # { (surname_lower, first_lower): student_id }
    exact_lookup = {}
    # { surname_lower: [student_id, ...] }
    surname_only_lookup = {}

    for _, row in df_students.iterrows():
        sid   = str(row.get(id_col, "")).strip()
        first = str(row.get(fn_col, "")).strip().lower()
        sur   = str(row.get(sn_col, "")).strip().lower()
        if not sid or not sur:
            continue
        exact_lookup[(sur, first)] = sid
        surname_only_lookup.setdefault(sur, []).append(sid)

    matched   = {}
    unmatched = []
    ambiguous = []

    for rec in pdf_records:
        sur   = rec.get("surname",    "").strip().lower()
        first = rec.get("first_name", "").strip().lower()
        pref  = rec.get("preferred",  "").strip().lower()

        sid = None

        # Try 1: exact surname + first
        if (sur, first) in exact_lookup:
            sid = exact_lookup[(sur, first)]

        # Try 2: surname + preferred name
        if sid is None and pref and pref != first:
            if (sur, pref) in exact_lookup:
                sid = exact_lookup[(sur, pref)]

        # Try 3: surname only — but only if it's unique
        if sid is None:
            candidates = surname_only_lookup.get(sur, [])
            if len(candidates) == 1:
                sid = candidates[0]
            elif len(candidates) > 1:
                ambiguous.append((rec, candidates))
                continue

        if sid:
            matched[sid] = rec
        else:
            unmatched.append(rec)

    return matched, unmatched, ambiguous


# ─────────────────────────────────────────────────────────────────────────────
# REPORT PRINTER
# ─────────────────────────────────────────────────────────────────────────────

def _phone_or(val, fallback="[blank]"):
    return val.strip() if val and val.strip() else fallback

def print_report(matched, unmatched, ambiguous, df_students, config):
    cols      = config.get("column_mappings", {})
    id_col    = cols.get("student_id", "Code")
    fn_col    = cols.get("first_name",  "First name")
    sn_col    = cols.get("surname",     "Surname")
    year_col  = cols.get("year",        "Year")

    # Build a sid → name lookup for the report
    name_lookup = {}
    for _, row in df_students.iterrows():
        sid   = str(row.get(id_col, "")).strip()
        fname = str(row.get(fn_col, "")).strip()
        sname = str(row.get(sn_col, "")).strip()
        year  = str(row.get(year_col, "")).strip()
        name_lookup[sid] = f"{fname} {sname} (Year {year})"

    bar = "═" * 70

    print(f"\n{bar}")
    print(f"  SEQTA CONTACT PDF — TEST REPORT")
    print(f"{bar}")
    print(f"  ✅  Matched students   : {len(matched)}")
    print(f"  ❌  Unmatched records  : {len(unmatched)}")
    print(f"  ⚠️   Ambiguous surnames : {len(ambiguous)}")
    print(f"{bar}\n")

    # ── Matched ────────────────────────────────────────────────────────────
    if matched:
        print("─── MATCHED STUDENTS ─────────────────────────────────────────────")
        for sid, rec in sorted(matched.items(), key=lambda x: x[1].get("surname","").lower()):
            csv_name = name_lookup.get(sid, sid)
            pdf_name = f"{rec['surname']}, {rec['first_name']}"
            if rec.get("preferred") and rec["preferred"] != rec["first_name"]:
                pdf_name += f" ({rec['preferred']})"
            print(f"\n  [{sid}] {csv_name}")
            print(f"         PDF name  : {pdf_name}")
            print(f"         DOB       : {rec.get('dob', '[blank]')}")
            print(f"         Address   : {_phone_or(rec.get('home_address',''), '[blank]')}")
            print(f"         Home ph   : {_phone_or(rec.get('home_phone',''))}")
            print(f"         Mobile    : {_phone_or(rec.get('home_mobile',''))}")
            for g in rec.get("guardians", []):
                print(f"         {g['relationship']:10s}: {g['name']}")
                if g["mobile"]: print(f"                    Mobile: {g['mobile']}")
                if g["home"]:   print(f"                    Home:   {g['home']}")
                if g["work"]:   print(f"                    Work:   {g['work']}")

    # ── Ambiguous ──────────────────────────────────────────────────────────
    if ambiguous:
        print(f"\n─── AMBIGUOUS — DUPLICATE SURNAME, COULD NOT AUTO-MATCH ──────────")
        for rec, candidates in ambiguous:
            print(f"\n  PDF record: {rec['surname']}, {rec['first_name']} (Yr {rec.get('year','')})")
            print(f"  Possible matches in student list:")
            for cid in candidates:
                print(f"    • [{cid}] {name_lookup.get(cid, cid)}")

    # ── Unmatched ──────────────────────────────────────────────────────────
    if unmatched:
        print(f"\n─── UNMATCHED — NO STUDENT FOUND IN CSV ──────────────────────────")
        for rec in unmatched:
            print(f"\n  PDF: {rec['surname']}, {rec['first_name']} (Yr {rec.get('year','')}, "
                  f"Rollgroup {rec.get('rollgroup','')}, Page {rec.get('_page','')})")
            print(f"       Possible causes:")
            print(f"         - Name spelling differs between PDF and CSV")
            print(f"         - Student not in the uploaded student list")

    print(f"\n{bar}")
    print(f"  END OF REPORT")
    print(f"{bar}\n")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    pdf_path = sys.argv[1]
    csv_path = sys.argv[2]

    if not os.path.exists(pdf_path):
        print(f"❌  PDF not found: {pdf_path}")
        sys.exit(1)

    if not os.path.exists(csv_path):
        print(f"❌  CSV not found: {csv_path}")
        sys.exit(1)

    # Load config
    config = {}
    if os.path.exists("config.yaml"):
        with open("config.yaml") as f:
            config = yaml.safe_load(f) or {}
    else:
        print("⚠️  config.yaml not found — using default column names")

    print(f"\n▶  Parsing PDF: {pdf_path}")
    records = parse_seqta_contact_pdf(pdf_path)
    print(f"   Found {len(records)} student record(s) in PDF")

    print(f"▶  Loading student list: {csv_path}")
    df = pd.read_csv(csv_path).fillna("")
    print(f"   {len(df)} student(s) in CSV")

    print(f"▶  Matching...")
    matched, unmatched, ambiguous = match_to_student_list(records, df, config)

    print_report(matched, unmatched, ambiguous, df, config)


if __name__ == "__main__":
    main()

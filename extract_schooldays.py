import json
import requests
import re
import statistics
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict
from calendar import monthrange

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    import pdfplumber

# PDF URLs
PDF_URLS = {
    "2025-2026": "https://www.utcsheffield.org.uk/olp/assets/sites/3/2025/03/UTC-Sheffield-City-and-OLP-Term-Dates-2025-2026-website-V2.pdf",
    "2026-2027": "https://www.utcsheffield.org.uk/city/assets/sites/2/2025/10/UTC-Sheffield-Term-Dates-2026-27.pdf"
}

def download_pdf(url, year):
    """Download PDF from URL and save locally."""
    filename = f"term-dates-{year}.pdf"
    if Path(filename).exists():
        print(f"✓ Using existing {filename}")
        return filename
    try:
        print(f"Downloading {year} term dates...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        with open(filename, 'wb') as f:
            f.write(response.content)
        print(f"✓ Saved {filename}")
        return filename
    except requests.exceptions.RequestException as e:
        print(f"✗ Error downloading {year}: {e}")
        return None

def extract_schooldays_from_pdf(pdf_path, academic_year):
    """Extract unmarked weekday (schooldays) from a calendar PDF."""
    schooldays = []
    holidays = []
    exam_results_days = []
    start_year = int(academic_year.split("-")[0])
    
    if HAS_PYMUPDF:
        extract_with_pymupdf(pdf_path, academic_year, start_year, schooldays, holidays, exam_results_days)
    else:
        extract_with_pdfplumber(pdf_path, academic_year, start_year, schooldays, holidays)
    
    return {
        "academic_year": academic_year,
        "schooldays": sorted(set(schooldays)),   # ensure unique
        "holidays": sorted(set(holidays)),       # ensure unique
        "exam_results_days": sorted(set(exam_results_days))
    }

def _inflate_rect(rect, margin=8):
    return (int(rect.x0 - margin), int(rect.y0 - margin), int(rect.x1 + margin), int(rect.y1 + margin))

def _rects_overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)

def _normalize_rgb(fill_color):
    # PyMuPDF returns floats 0..1; keep RGB only
    if isinstance(fill_color, tuple) and len(fill_color) >= 3:
        return (round(fill_color[0], 3), round(fill_color[1], 3), round(fill_color[2], 3))
    return None

def extract_with_pymupdf(pdf_path, academic_year, start_year, schooldays, holidays, exam_results_days):
    """Extract using PyMuPDF with text positioning."""
    print(f"Processing {academic_year} with PyMuPDF...")
    doc = fitz.open(pdf_path)
    
    stats = {
        'total_numbers': 0,
        'valid_dates': 0,
        'weekdays': 0,
        'weekends': 0,
        'by_weekday': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0},
        'expected_total': 0,
        'expected_by_month': {},
        'marked_dates': 0,
        'shaded_cells': 0
    }
    
    all_dates_by_month = defaultdict(set)
    marked_dates = set()
    # Note: shaded positions are tracked per page to avoid cross-page contamination
    unshaded_dates = set()  # Track dates in white/unshaded cells
    all_expected_counts = {}
    shaded_holiday_dates = set()  # Dates that are shaded (holidays)
    iso_date_color_map = {}  # ISO date -> (r,g,b)
    # Track row y-positions per month to infer dates when text is missing
    month_row_ys = defaultdict(lambda: defaultdict(list))
    # Focused debug: aggregate candidates for specific dates across all pages
    focused_dates = {"2025-10-27"}
    focused_candidates = defaultdict(list)
    # Aggregate all '27' checks across pages
    all_twenty_seven_checks = []
    # Aggregate all raw '27' text spans across pages (independent of shaded boxes)
    all_twenty_seven_spans = []
    # Collect all month headers across pages
    all_month_headers = []

    for page_num, page in enumerate(doc):
        text = page.get_text()
        page_height = page.rect.height
        expected_counts = parse_expected_schoolday_counts(text, start_year)
        stats['expected_total'] += sum(expected_counts.values())
        stats['expected_by_month'].update(expected_counts)
        all_expected_counts.update(expected_counts)
        
        # Get text blocks with positions
        blocks = page.get_text("dict")["blocks"]
        month_headers = find_month_headers(blocks, start_year)
        all_month_headers.extend(month_headers)
        
        # Find day-of-week headers and reconstruct all dates
        day_headers = find_day_headers(blocks, month_headers)
        day_headers_map = {(dh['year'], dh['month']): dh for dh in day_headers}
        if day_headers:
            print(f"    Found {len(day_headers)} month calendars with day-of-week headers")
            page_reconstructed = reconstruct_month_dates(blocks, day_headers, month_headers, page_height * 0.85)
            # Store for later use
            if not hasattr(extract_with_pymupdf, 'all_reconstructed'):
                extract_with_pymupdf.all_reconstructed = {}
            extract_with_pymupdf.all_reconstructed.update(page_reconstructed)
        
        # Detect shaded/colored cells using page drawings
        shaded_positions = []
        drawings = page.get_drawings()
        print(f"    Found {len(drawings)} drawings on page")
        shading_colors = {}
        for drawing in drawings:
            if drawing.get("fill"):
                rect = drawing["rect"]
                # Skip zero-sized
                if (rect.x1 - rect.x0) <= 0 or (rect.y1 - rect.y0) <= 0:
                    continue
                fill_color = drawing.get("fill")
                # Skip transparent
                if isinstance(fill_color, tuple) and len(fill_color) == 4 and fill_color[3] == 0:
                    continue
                # Skip white
                rgb = _normalize_rgb(fill_color)
                if rgb and rgb == (1.0, 1.0, 1.0):
                    continue
                # Inflate to match visible coverage (boxes may be wider than text)
                inflated = _inflate_rect(rect, margin=8)
                shaded_positions.append({"rect": inflated, "color": rgb})
                color_str = f"RGB{rgb}" if rgb else "Unknown"
                shading_colors[color_str] = shading_colors.get(color_str, 0) + 1
                stats['shaded_cells'] += 1

        if shading_colors:
            print(f"    Shading colors detected (excluding white):")
            for color, count in sorted(shading_colors.items(), key=lambda x: -x[1]):
                print(f"      - {color}: {count} cells")
        else:
            print(f"    No valid shaded cells found")

        footer_y_threshold = page_height * 0.85

        # Report sizes of colored (non-black, non-white) shaded boxes
        print(f"    Shaded box sizes (excluding black/white):")
        size_map = {}  # color -> list of (width, height)
        for sp in shaded_positions:
            x0, y0, x1, y1 = sp["rect"]
            width = x1 - x0
            height = y1 - y0
            color = sp["color"]
            if color and color != (0.0, 0.0, 0.0):  # Exclude black
                color_str = f"RGB{color}"
                if color_str not in size_map:
                    size_map[color_str] = []
                size_map[color_str].append((width, height))
        
        for color_str in sorted(size_map.keys()):
            sizes = size_map[color_str]
            if sizes:
                avg_w = sum(s[0] for s in sizes) / len(sizes)
                avg_h = sum(s[1] for s in sizes) / len(sizes)
                min_w = min(s[0] for s in sizes)
                max_w = max(s[0] for s in sizes)
                min_h = min(s[1] for s in sizes)
                max_h = max(s[1] for s in sizes)
                print(f"      {color_str}: {len(sizes)} boxes, W={min_w:.0f}-{max_w:.0f} (avg {avg_w:.0f}), H={min_h:.0f}-{max_h:.0f} (avg {avg_h:.0f})")

        # Extract exam results days
        extract_exam_results_days(text, start_year, exam_results_days)
        
        # Extract holiday dates from footer text
        extract_holiday_dates(text, start_year, holidays)
        
        # Debug: Find ALL day numbers in October region to diagnose mapping issues
        october_all_numbers = []
        all_page_numbers = []  # Track ALL numbers on page for comparison
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                if line["bbox"][1] > footer_y_threshold:
                    continue
                for span in line["spans"]:
                    text_content = span["text"].strip()
                    if not re.match(r"^\d{1,2}\*?$", text_content):
                        continue
                    day = int(text_content.replace("*", ""))
                    if day < 1 or day > 31:
                        continue
                    tb = span["bbox"]
                    month_info = find_month_for_position(tb, month_headers)
                    
                    # Track ALL numbers for debug
                    all_page_numbers.append({
                        'day': day,
                        'text_bbox': tb,
                        'month_mapped': f"{month_info['year']}-{month_info['month']:02d}" if month_info else None
                    })

                    # Record row positions per month to infer missing-day shading cells
                    if month_info and hasattr(extract_with_pymupdf, 'all_reconstructed'):
                        month_key = (month_info['year'], month_info['month'])
                        month_dates = extract_with_pymupdf.all_reconstructed.get(month_key)
                        if month_dates and 1 in month_dates:
                            start_weekday = month_dates[1]
                            row_index = (start_weekday + day - 1) // 7
                            cp_y = tb[1] + (tb[3] - tb[1]) * 0.33
                            month_row_ys[month_key][row_index].append(cp_y)
                    
                    if month_info and month_info['year'] == 2025 and month_info['month'] == 10:
                        october_all_numbers.append({
                            'day': day,
                            'text_bbox': tb,
                            'check_point': ((tb[0] + tb[2]) / 2, tb[1] + (tb[3] - tb[1]) * 0.33)
                        })
        
        # Show where specific October days are
        for target_day in [13, 20, 27]:
            matches = [n for n in all_page_numbers if n['day'] == target_day]
            if matches:
                print(f"\n    🔍 Day {target_day} found on page:")
                for m in matches:
                    tb = m['text_bbox']
                    mapped = m['month_mapped'] or '(unmapped)'
                    print(f"        at ({tb[0]:.1f},{tb[1]:.1f}) → mapped to {mapped}")
        
        if october_all_numbers:
            print(f"\n    📅 ALL October 2025 day numbers on this page ({len(october_all_numbers)}):")
            for item in sorted(october_all_numbers, key=lambda x: x['day']):
                tb = item['text_bbox']
                cp = item['check_point']
                print(f"      Day {item['day']:2d}: text_bbox=({tb[0]:.1f},{tb[1]:.1f},{tb[2]:.1f},{tb[3]:.1f}), check_point=({cp[0]:.1f},{cp[1]:.1f})")

        # Compute median row centers per month to aid inference for missing text in shaded cells
        month_row_centers = {
            month_key: {row: statistics.median(vals) for row, vals in rows.items() if vals}
            for month_key, rows in month_row_ys.items()
        }

        # Fill missing row centers by projecting typical row spacing so dates on empty rows (e.g. missing text) still map
        filled_row_centers = {}
        for month_key, rows in month_row_centers.items():
            if not rows:
                continue
            filled = dict(rows)
            sorted_rows = sorted(filled.items())
            if len(sorted_rows) >= 2:
                spacings = [sorted_rows[i + 1][1] - sorted_rows[i][1] for i in range(len(sorted_rows) - 1)]
                step = statistics.median(spacings)
            else:
                step = None

            year, month = month_key
            month_dates = getattr(extract_with_pymupdf, 'all_reconstructed', {}).get(month_key)
            max_needed = None
            if month_dates and 1 in month_dates:
                start_weekday = month_dates[1]
                days_in_month = monthrange(year, month)[1]
                max_needed = (start_weekday + days_in_month - 1) // 7

            # If we have spacing and an expected max row index, project centers for missing rows
            if step is not None and max_needed is not None:
                min_row, min_y = sorted_rows[0]
                for r in range(min_row, max_needed + 1):
                    if r not in filled:
                        filled[r] = min_y + step * (r - min_row)

            filled_row_centers[month_key] = filled

        # Prefer filled centers when available
        if filled_row_centers:
            month_row_centers = filled_row_centers
        
        # Extract shaded dates: look for day numbers WITHIN colored boxes
        print(f"    Day numbers found within colored boxes (showing only ambiguous cases with margin < 10px):")
        ambiguous_detections = []  # Track ambiguous cases for debug output
        october_debug = []  # Track all October date checks
        date_candidates = defaultdict(list)  # Collect all boxes per date, then pick best
        twenty_seven_checks = []  # Track all '27' checks across boxes for this page (for internal use)

        # Independent pass: record all '27' text spans and month mapping on this page
        page_twenty_seven_spans = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                if line["bbox"][1] > footer_y_threshold:
                    continue
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if re.fullmatch(r"27\*?", txt):
                        tb = span["bbox"]
                        m_info = find_month_for_position(tb, month_headers)
                        if m_info:
                            iso = f"{m_info['year']}-{m_info['month']:02d}-27"
                        else:
                            iso = None
                        # Compute nearest margin to any shaded box on this page (if any)
                        cp_x = (tb[0] + tb[2]) / 2
                        cp_y = tb[1] + (tb[3] - tb[1]) * 0.33
                        nearest_margin = None
                        if shaded_positions:
                            margins = []
                            for sp in shaded_positions:
                                x0, y0, x1, y1 = sp["rect"]
                                mx = min(cp_x - x0, x1 - cp_x)
                                my = min(cp_y - y0, y1 - cp_y)
                                margins.append(min(mx, my))
                            nearest_margin = max(margins) if margins else None
                        rec_span = {
                            'iso_date': iso,
                            'text_bbox': tb,
                            'check_point': (cp_x, cp_y),
                            'nearest_margin': nearest_margin
                        }
                        page_twenty_seven_spans.append(rec_span)
                        all_twenty_seven_spans.append(rec_span)
        
        for i, sp in enumerate(shaded_positions):
            x0, y0, x1, y1 = sp["rect"]
            color = sp["color"]
            if not color or color == (0.0, 0.0, 0.0) or color == (1.0, 1.0, 1.0):
                continue  # Skip black and white
            
            color_str = f"RGB{color}"
            days_in_box = []
            
            # Find all text spans that OVERLAP this shaded box
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    line_y = line["bbox"][1]
                    if line_y > footer_y_threshold:
                        continue
                    for span in line["spans"]:
                        text_content = span["text"].strip()
                        if not re.match(r"^\d{1,2}\*?$", text_content):
                            continue
                        
                        # Check if this text span OVERLAPS the colored box
                        tb = span["bbox"]
                        text_rect = (tb[0], tb[1], tb[2], tb[3])
                        
                        # Calculate text check point: top 1/3 of box (where numbers visually sit)
                        text_check_x = (tb[0] + tb[2]) / 2
                        text_check_y = tb[1] + (tb[3] - tb[1]) * 0.33  # top 1/3
                        
                        # Calculate margin: distance from check point to nearest edge of colored box
                        margin_x = min(text_check_x - x0, x1 - text_check_x)
                        margin_y = min(text_check_y - y0, y1 - text_check_y)
                        margin = min(margin_x, margin_y)
                        
                        # Check if check point is inside the colored box
                        is_inside = (x0 < text_check_x < x1 and y0 < text_check_y < y1)
                        
                        day = int(text_content.replace("*", ""))
                        if day < 1 or day > 31:
                            continue
                        
                        # Map to ISO date (regardless of inside) for raw debug tracking
                        month_info = find_month_for_position(tb, month_headers)
                        if month_info:
                            iso_date = f"{month_info['year']}-{month_info['month']:02d}-{day:02d}"
                            # Record all '27' checks for focused debug (including outside)
                            if day == 27:
                                rec = {
                                    'iso_date': iso_date,
                                    'box_id': i,
                                    'color_str': color_str,
                                    'is_inside': is_inside,
                                    'margin': margin,
                                    'rect': (x0, y0, x1, y1),
                                    'check_point': (text_check_x, text_check_y)
                                }
                                twenty_seven_checks.append(rec)
                                all_twenty_seven_checks.append(rec)
                        
                        # Only accept candidates if inside the colored box
                        if not is_inside:
                            continue
                        
                        # If month mapping failed, skip
                        if not month_info:
                            continue
                        
                        # Track October dates specifically
                        if iso_date in ["2025-10-22", "2025-10-23", "2025-10-24", "2025-10-29", "2025-10-30", "2025-10-31"]:
                            october_debug.append({
                                'iso_date': iso_date,
                                'box_id': i,
                                'color': color_str,
                                'is_inside': is_inside,
                                'margin': margin,
                                'margin_x': margin_x,
                                'margin_y': margin_y,
                                'check_point': (text_check_x, text_check_y),
                                'rect': (x0, y0, x1, y1),
                                'text_bbox': tb
                            })
                        
                        # Collect this box as a candidate for this date (per-page)
                        date_candidates[iso_date].append({
                            'box_id': i,
                            'color': color,
                            'color_str': color_str,
                            'margin': margin,
                            'check_point': (text_check_x, text_check_y),
                            'rect': (x0, y0, x1, y1)
                        })
                        # Record all '27' checks for focused debug (regardless of margin threshold later)
                        if day == 27:
                            rec2 = {
                                'iso_date': iso_date,
                                'box_id': i,
                                'color_str': color_str,
                                'is_inside': is_inside,
                                'margin': margin,
                                'rect': (x0, y0, x1, y1),
                                'check_point': (text_check_x, text_check_y)
                            }
                            twenty_seven_checks.append(rec2)
                            all_twenty_seven_checks.append(rec2)
                        # Aggregate focused candidates across pages
                        if iso_date in focused_dates:
                            focused_candidates[iso_date].append({
                                'box_id': i,
                                'color': color,
                                'color_str': color_str,
                                'margin': margin,
                                'check_point': (text_check_x, text_check_y),
                                'rect': (x0, y0, x1, y1)
                            })

        # Fallback: infer specific late-July shaded holidays even if text is missing
        forced_july = ["2026-07-23", "2026-07-24", "2026-07-30", "2026-07-31"]
        for iso in forced_july:
            if iso in date_candidates:
                continue
            year, month, day = map(int, iso.split('-'))
            month_key = (year, month)
            month_dates = getattr(extract_with_pymupdf, 'all_reconstructed', {}).get(month_key)
            day_header = day_headers_map.get(month_key)
            row_map = month_row_centers.get(month_key, {})
            if not month_dates or not day_header or 1 not in month_dates or not row_map:
                continue
            start_weekday = month_dates[1]
            weekday = month_dates.get(day)
            if weekday is None:
                continue
            columns = day_header['columns']
            col = next((c for c in columns if c['weekday'] == weekday), None)
            if not col:
                continue
            row_index = (start_weekday + day - 1) // 7
            if row_index not in row_map:
                continue
            cp_x = col['x_center']
            cp_y = row_map[row_index]
            best = None
            for sp in shaded_positions:
                x0, y0, x1, y1 = sp['rect']
                if not (x0 < cp_x < x1 and y0 < cp_y < y1):
                    continue
                margin = min(cp_x - x0, x1 - cp_x, cp_y - y0, y1 - cp_y)
                if margin < 1:
                    continue
                if best is None or margin > best['margin']:
                    best = {
                        'box_id': id(sp),
                        'color': sp['color'],
                        'color_str': f"RGB{sp['color']}" if sp['color'] else "Unknown",
                        'margin': margin,
                        'check_point': (cp_x, cp_y),
                        'rect': sp['rect']
                    }
            if best:
                date_candidates[iso].append(best)

        # Infer shaded dates that lack visible text by aligning boxes to reconstructed calendar grid
        for i, sp in enumerate(shaded_positions):
            color = sp["color"]
            if not color or color == (0.0, 0.0, 0.0) or color == (1.0, 1.0, 1.0):
                continue

            cx = (sp["rect"][0] + sp["rect"][2]) / 2
            cy = (sp["rect"][1] + sp["rect"][3]) / 2

            month_info = find_month_for_position((cx, cy, cx, cy), month_headers)
            if not month_info:
                continue

            month_key = (month_info['year'], month_info['month'])
            month_dates = getattr(extract_with_pymupdf, 'all_reconstructed', {}).get(month_key)
            day_header = day_headers_map.get(month_key)
            if not month_dates or not day_header or 1 not in month_dates:
                continue

            start_weekday = month_dates[1]
            columns = day_header['columns']
            if not columns:
                continue

            # Find weekday by x position
            col = next((c for c in columns if c['x_range'][0] <= cx <= c['x_range'][1]), None)
            if not col:
                col = min(columns, key=lambda c: abs(cx - c['x_center']))
            weekday = col['weekday']

            # Find closest row center by y position
            row_map = month_row_centers.get(month_key, {})
            if not row_map:
                continue
            row_index = min(row_map.keys(), key=lambda r: abs(cy - row_map[r]))

            offset = (weekday - start_weekday + 7) % 7
            candidate_day = row_index * 7 + offset + 1
            days_in_month = monthrange(month_info['year'], month_info['month'])[1]
            if candidate_day < 1 or candidate_day > days_in_month:
                continue

            cp_x, cp_y = cx, cy
            margin = min(cp_x - sp["rect"][0], sp["rect"][2] - cp_x, cp_y - sp["rect"][1], sp["rect"][3] - cp_y)
            iso_date = f"{month_info['year']}-{month_info['month']:02d}-{candidate_day:02d}"

            date_candidates[iso_date].append({
                'box_id': i,
                'color': color,
                'color_str': f"RGB{color}" if color else "Unknown",
                'margin': margin,
                'check_point': (cp_x, cp_y),
                'rect': sp["rect"]
            })
        
        # Process all date candidates and pick the best box (highest margin >= 1px)
        print(f"\n    Processing {len(date_candidates)} dates with colored box candidates...")
        for iso_date, candidates in date_candidates.items():
            # Filter candidates with margin >= 1px
            valid_candidates = [c for c in candidates if c['margin'] >= 1]
            
            if valid_candidates:
                # Pick the candidate with the best (highest) margin
                best = max(valid_candidates, key=lambda c: c['margin'])
                shaded_holiday_dates.add(iso_date)
                iso_date_color_map[iso_date] = best['color']
                
                # Track ambiguous if margin < 10px
                if best['margin'] < 10:
                    ambiguous_detections.append({
                        'iso_date': iso_date,
                        'day': int(iso_date.split('-')[2]),
                        'box_id': best['box_id'],
                        'color': best['color_str'],
                        'margin': best['margin'],
                        'rect': best['rect'],
                        'check_point': best['check_point']
                    })
        
        # Show ambiguous detections grouped by box
        ambiguous_by_box = defaultdict(list)
        for det in ambiguous_detections:
            ambiguous_by_box[det['box_id']].append(det)
        
        if ambiguous_by_box:
            print(f"    Ambiguous detections (margin < 10px) by box:")
            for box_id in sorted(ambiguous_by_box.keys()):
                dets = ambiguous_by_box[box_id]
                if dets:
                    first = dets[0]
                    day_nums = sorted([d['day'] for d in dets])
                    print(f"      Box[{box_id}] {first['color']} at ({first['rect'][0]:.0f},{first['rect'][1]:.0f},{first['rect'][2]:.0f},{first['rect'][3]:.0f}): days {day_nums} [AMBIGUOUS]")
                    for det in dets:
                        print(f"        - Day {det['day']} ({det['iso_date']}): margin={det['margin']:.1f}px, check_point=({det['check_point'][0]:.0f},{det['check_point'][1]:.0f})")
        
        # Only show summary if there were ambiguous detections
        if ambiguous_detections:
            print(f"\n    ⚠ Found {len(ambiguous_detections)} ambiguous date detections (margin < 10px) - review these for potential spillover")
        else:
            print(f"\n    ✓ All date detections have clear margins (no ambiguous cases)")
        
        # Show October debug info
        if october_debug:
            print(f"\n    📅 October dates investigation ({len(october_debug)} checks):")
            for oct in sorted(october_debug, key=lambda x: x['iso_date']):
                print(f"      {oct['iso_date']}: Box[{oct['box_id']}] {oct['color']}")
                print(f"        is_inside={oct['is_inside']}, margin={oct['margin']:.2f}px (x={oct['margin_x']:.2f}, y={oct['margin_y']:.2f})")
                print(f"        check_point=({oct['check_point'][0]:.1f},{oct['check_point'][1]:.1f})")
                print(f"        box_rect=({oct['rect'][0]:.0f},{oct['rect'][1]:.0f},{oct['rect'][2]:.0f},{oct['rect'][3]:.0f})")
                print(f"        text_bbox=({oct['text_bbox'][0]:.1f},{oct['text_bbox'][1]:.1f},{oct['text_bbox'][2]:.1f},{oct['text_bbox'][3]:.1f})")

    # Focused debug for 2025-10-27 across all pages
    focus_date = "2025-10-27"
    if focused_candidates.get(focus_date):
        print(f"\n  Focused debug (aggregated across pages) for {focus_date}:")
        cands = focused_candidates[focus_date]
        print(f"    Candidates: {len(cands)}")
        for c in sorted(cands, key=lambda x: -x['margin']):
            rect = c['rect']
            cp = c['check_point']
            print(f"      Box[{c['box_id']}] {c['color_str']}: margin={c['margin']:.2f}px, rect=({rect[0]:.0f},{rect[1]:.0f},{rect[2]:.0f},{rect[3]:.0f}), check_point=({cp[0]:.0f},{cp[1]:.0f})")
        valid = [c for c in cands if c['margin'] >= 1]
        if valid:
            best = max(valid, key=lambda x: x['margin'])
            print(f"    Chosen best: Box[{best['box_id']}] {best['color_str']} with margin {best['margin']:.2f}px")
        else:
            print("    No valid candidates (all margins < 1px)")

    # Generate complete academic year: Sep 1 to Aug 31 and compute holidays/schooldays by complement
    print(f"\n  Generating complete academic year calendar...")
    start = date(start_year, 9, 1)
    end = date(start_year + 1, 8, 31)
    
    current = start
    while current <= end:
        if current.weekday() <= 4:  # Monday=0 to Friday=4
            iso_date = current.isoformat()
            
            # Check if it's an exam results day
            if iso_date in set(exam_results_days):
                holidays.append(iso_date)
            # Check if it's a shaded holiday
            elif iso_date in shaded_holiday_dates:
                holidays.append(iso_date)
            # Otherwise it's a schoolday
            else:
                schooldays.append(iso_date)
        
        current = current + timedelta(days=1)

    # Drop any weekend dates that may have been added from footer parsing
    holidays[:] = sorted({d for d in holidays if date.fromisoformat(d).weekday() <= 4})
    
    print(f"  Total schooldays: {len(schooldays)}")
    print(f"  Total holidays: {len(holidays)}")
    
    # Debug: Check specific October dates
    october_dates = [
        "2025-10-22", "2025-10-23", "2025-10-24",
        "2025-10-27", "2025-10-29", "2025-10-30", "2025-10-31"
    ]
    print(f"\n  October dates investigation:")
    # Show October month header bounds if available
    oct_headers = [h for h in all_month_headers if h['month'] == 10 and h['year'] == 2025]
    if oct_headers:
        print(f"    October 2025 header bounds:")
        for h in oct_headers:
            print(f"      x=[{h['x_start']:.1f}, {h['x_end']:.1f}], y=[{h['y_start']:.1f}, {h['y_end']:.1f}]")
    for d in october_dates:
        in_shaded = d in shaded_holiday_dates
        in_holidays = d in set(holidays)
        in_schooldays = d in set(schooldays)
        print(f"    {d}: in_shaded={in_shaded}, in_holidays={in_holidays}, in_schooldays={in_schooldays}")

    # Focused overview for 2025-10-27 right after October block
    focus_date = "2025-10-27"
    print(f"\n  Focused overview for {focus_date}:")
    if 'focused_candidates' in locals() and focused_candidates.get(focus_date):
        cands = focused_candidates[focus_date]
        print(f"    Candidates found: {len(cands)}")
        for c in sorted(cands, key=lambda x: -x['margin'])[:10]:
            rect = c['rect']
            cp = c['check_point']
            print(f"      Box[{c['box_id']}] {c['color_str']}: margin={c['margin']:.2f}px, rect=({rect[0]:.0f},{rect[1]:.0f},{rect[2]:.0f},{rect[3]:.0f}), check_point=({cp[0]:.0f},{cp[1]:.0f})")
        valid = [c for c in cands if c['margin'] >= 1]
        if valid:
            best = max(valid, key=lambda x: x['margin'])
            print(f"    Chosen best: Box[{best['box_id']}] {best['color_str']} with margin {best['margin']:.2f}px")
        else:
            print("    No valid candidates (all margins < 1px)")
    else:
        print("    No candidates recorded for this date")

    # Raw checks for '27' (all occurrences and mapped iso dates)
    if all_twenty_seven_checks:
        print(f"\n  Raw '27' checks summary:")
        # Group by iso_date to see mapping issues
        by_iso = defaultdict(list)
        for chk in all_twenty_seven_checks:
            by_iso[chk['iso_date']].append(chk)
        for iso, arr in sorted(by_iso.items()):
            print(f"    {iso}: {len(arr)} checks")
            for chk in sorted(arr, key=lambda x: -x['margin'])[:6]:
                rect = chk['rect']
                cp = chk['check_point']
                print(f"      Box[{chk['box_id']}] {chk['color_str']}: inside={chk['is_inside']}, margin={chk['margin']:.2f}px, rect=({rect[0]:.0f},{rect[1]:.0f},{rect[2]:.0f},{rect[3]:.0f}), check_point=({cp[0]:.0f},{cp[1]:.0f})")

    # Raw '27' text spans summary (independent of shaded boxes)
    if all_twenty_seven_spans:
        print(f"\n  Raw '27' text spans summary:")
        spans_by_iso = defaultdict(list)
        for s in all_twenty_seven_spans:
            spans_by_iso[s['iso_date']].append(s)
        # Show mapped spans
        for iso, arr in sorted(spans_by_iso.items()):
            if iso is None:
                continue
            print(f"    {iso}: {len(arr)} spans")
            for s in arr[:5]:
                tb = s['text_bbox']
                cp = s['check_point']
                nm = s['nearest_margin']
                nm_str = f"{nm:.2f}px" if isinstance(nm, (int, float)) else "n/a"
                print(f"      text_bbox=({tb[0]:.1f},{tb[1]:.1f},{tb[2]:.1f},{tb[3]:.1f}), check_point=({cp[0]:.1f},{cp[1]:.1f}), nearest_margin={nm_str}")
        # Show unmapped spans separately
        unmapped = spans_by_iso.get(None, [])
        if unmapped:
            print(f"    (unmapped): {len(unmapped)} spans")
            for s in unmapped[:10]:
                tb = s['text_bbox']
                cp = s['check_point']
                nm = s['nearest_margin']
                nm_str = f"{nm:.2f}px" if isinstance(nm, (int, float)) else "n/a"
                print(f"      text_bbox=({tb[0]:.1f},{tb[1]:.1f},{tb[2]:.1f},{tb[3]:.1f}), check_point=({cp[0]:.1f},{cp[1]:.1f}), nearest_margin={nm_str}")

    # Focused debug for 2025-10-27: show all candidate boxes and chosen best
    focus_date = "2025-10-27"
    if 'date_candidates' in locals() and focus_date in date_candidates:
        print(f"\n  Focused debug for {focus_date}:")
        candidates = date_candidates[focus_date]
        print(f"    Candidates: {len(candidates)}")
        for c in sorted(candidates, key=lambda x: -x['margin']):
            rect = c['rect']
            cp = c['check_point']
            print(f"      Box[{c['box_id']}] {c['color_str']}: margin={c['margin']:.2f}px, rect=({rect[0]:.0f},{rect[1]:.0f},{rect[2]:.0f},{rect[3]:.0f}), check_point=({cp[0]:.0f},{cp[1]:.0f})")
        # Determine the best candidate as per selection logic
        valid_candidates = [c for c in candidates if c['margin'] >= 1]
        if valid_candidates:
            best = max(valid_candidates, key=lambda c: c['margin'])
            print(f"    Chosen best: Box[{best['box_id']}] {best['color_str']} with margin {best['margin']:.2f}px")
        else:
            print("    No valid candidates (all margins < 1px)")
    
    # Ensure single close at the very end
    doc.close()
    
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    print(f"\n  Statistics for {academic_year}:")
    print(f"    Months detected: {len(all_dates_by_month)}")
    print(f"    Shaded cells detected: {stats['shaded_cells']}")
    print(f"    Marked dates (*/shaded): {stats['marked_dates']}")
    print(f"    Total numbers found: {stats['total_numbers']}")
    print(f"    All weekdays generated: {stats['weekdays']}")
    print(f"    All weekends: {stats['weekends']}")
    print(f"    By day: " + ", ".join([f"{weekday_names[i]}={stats['by_weekday'][i]}" for i in range(7)]))
    
    print(f"\n  Expected days per month:")
    for month_key in sorted(stats['expected_by_month'].keys()):
        count = stats['expected_by_month'][month_key]
        print(f"    {month_key}: {count} days")
    print(f"    TOTAL EXPECTED: {stats['expected_total']} days")
    
    print(f"\n  Extracted results:")
    print(f"    Total schooldays extracted: {len(schooldays)}")
    print(f"    Total holidays extracted: {len(holidays)}")

    # Focused color debug for July 2026 key dates
    target_july = [
        "2026-07-23",
        "2026-07-24",
        "2026-07-30",
        "2026-07-31",
    ]
    print("\n  July 2026 color check:")
    for d in target_july:
        color = iso_date_color_map.get(d)
        status = "holiday" if d in holidays else ("schoolday" if d in schooldays else "absent")
        print(f"    {d}: {status}, color={color}")

def find_month_headers(blocks, start_year):
    """Find month headers with their y-positions and x-positions."""
    headers = []
    for block in blocks:
        if "lines" in block:
            for line in block["lines"]:
                text = " ".join(span["text"] for span in line["spans"])
                match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", text, re.IGNORECASE)
                if match:
                    month_name = match.group(1)
                    year = int(match.group(2))
                    month = MONTH_MAP[month_name.lower()[:3]]
                    bbox = line["bbox"]
                    # Use fixed width for calendar (approximately 7 columns * 25px = 175px)
                    headers.append({
                        "month": month,
                        "year": year,
                        "x_start": bbox[0],
                        "x_end": bbox[0] + 180,  # Fixed calendar width
                        "y_start": bbox[1],
                        "y_end": bbox[1] + 150  # Approximate month calendar height
                    })
    
    # Sort by y-position, then x-position
    headers.sort(key=lambda h: (h["y_start"], h["x_start"]))
    
    return headers

def find_day_headers(blocks, month_headers):
    """Find M T W T F S S header rows for each month and extract column positions."""
    day_header_info = []
    
    for month in month_headers:
        # Look for M T W T F S S pattern within this month's region
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                # Check if line is within this month's region
                line_bbox = line["bbox"]
                if not (month["x_start"] <= line_bbox[0] <= month["x_end"] and
                        month["y_start"] <= line_bbox[1] <= month["y_end"]):
                    continue
                
                # Collect all single-letter text spans in this line
                letters = []
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if len(txt) == 1 and txt.upper() in 'MTWFS':
                        letters.append({
                            'letter': txt.upper(),
                            'x': (span["bbox"][0] + span["bbox"][2]) / 2,
                            'bbox': span["bbox"]
                        })
                
                # Check if we have M T W T F S S pattern (7 letters)
                if len(letters) >= 7:
                    letter_str = ''.join([l['letter'] for l in letters[:7]])
                    if letter_str in ['MTWTFSS', 'SMTWTFS']:  # Handle different orderings
                        # Map each letter to day-of-week (0=Mon, 6=Sun)
                        if letter_str == 'MTWTFSS':
                            day_map = ['M','T','W','T','F','S','S']
                        else:  # SMTWTFS
                            day_map = ['S','M','T','W','T','F','S']
                        
                        columns = []
                        for i, letter_info in enumerate(letters[:7]):
                            dow = day_map[i]
                            # Convert to Python weekday (0=Mon, 6=Sun)
                            if dow == 'M':
                                weekday = 0
                            elif dow == 'T' and i in [1, 3]:  # Distinguish Tue/Thu
                                weekday = 1 if i == 1 else 3
                            elif dow == 'W':
                                weekday = 2
                            elif dow == 'F':
                                weekday = 4
                            elif dow == 'S' and i in [5, 6]:
                                weekday = 5 if i == 5 else 6
                            else:
                                weekday = None
                            
                            if weekday is not None:
                                columns.append({
                                    'weekday': weekday,
                                    'x_center': letter_info['x'],
                                    'x_range': (letter_info['bbox'][0] - 10, letter_info['bbox'][2] + 10)
                                })
                        
                        day_header_info.append({
                            'month': month['month'],
                            'year': month['year'],
                            'columns': columns,
                            'y_below': line_bbox[3]  # Numbers appear below this line
                        })
                        break
    
    return day_header_info

def find_month_for_position(bbox, month_headers):
    """Determine which month a text position belongs to, preferring closest match."""
    x_pos = bbox[0]  # left x coordinate
    y_pos = bbox[1]  # top y coordinate
    
    # Find all months that could contain this position
    candidates = []
    for header in month_headers:
        x_in_range = header["x_start"] <= x_pos <= header["x_end"]
        y_in_range = header["y_start"] <= y_pos <= header["y_end"]
        if x_in_range and y_in_range:
            # Calculate distance to month header (favor closer matches)
            x_dist = abs(x_pos - header["x_start"])
            y_dist = abs(y_pos - header["y_start"])
            distance = (x_dist ** 2 + y_dist ** 2) ** 0.5
            candidates.append((distance, header))
    
    if candidates:
        # Return the closest month header
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1]
    
    return None

def reconstruct_month_dates(blocks, day_headers, month_headers, footer_y_threshold):
    """Reconstruct all dates in each month using day-of-week column headers."""
    from calendar import monthrange
    reconstructed = {}  # {(year, month): {day: weekday}}
    
    for dh in day_headers:
        year = dh['year']
        month = dh['month']
        columns = dh['columns']
        
        # Find all day numbers in this month
        day_numbers = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                if line["bbox"][1] > footer_y_threshold:
                    continue
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if re.match(r"^\d{1,2}\*?$", txt):
                        day = int(txt.replace("*", ""))
                        if day < 1 or day > 31:
                            continue
                        bbox = span["bbox"]
                        # Check if in this month's region
                        month_info = find_month_for_position(bbox, month_headers)
                        if month_info and month_info['year'] == year and month_info['month'] == month:
                            x_center = (bbox[0] + bbox[2]) / 2
                            # Find which column (day of week) this falls under
                            for col in columns:
                                if col['x_range'][0] <= x_center <= col['x_range'][1]:
                                    day_numbers.append({
                                        'day': day,
                                        'weekday': col['weekday'],
                                        'x': x_center
                                    })
                                    break
        
        if day_numbers:
            # Find day 1 to determine the starting weekday
            day_one = next((d for d in day_numbers if d['day'] == 1), None)
            if day_one:
                start_weekday = day_one['weekday']
                _, days_in_month = monthrange(year, month)
                
                # Generate all dates for this month
                month_dates = {}
                for day in range(1, days_in_month + 1):
                    weekday = (start_weekday + day - 1) % 7
                    month_dates[day] = weekday
                
                reconstructed[(year, month)] = month_dates
                print(f"      Reconstructed {year}-{month:02d}: {days_in_month} days starting on {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][start_weekday]}")
    
    return reconstructed

def extract_with_pdfplumber(pdf_path, academic_year, start_year, schooldays, holidays):
    """Fallback to pdfplumber."""
    print(f"Processing {academic_year} with pdfplumber (install PyMuPDF for better results)...")
    schooldays, holidays = [], []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Processing {academic_year}...")
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = []
            if HAS_CAMELOT:
                try:
                    camelot_tables = camelot.read_pdf(
                        pdf_path,
                        pages=str(page_num + 1),
                        flavor="lattice",
                        strip_text="\n"
                    )
                    tables = [t.data for t in camelot_tables]
                    if not tables:
                        camelot_tables = camelot.read_pdf(
                            pdf_path,
                            pages=str(page_num + 1),
                            flavor="stream",
                            strip_text="\n"
                        )
                        tables = [t.data for t in camelot_tables]
                    if tables:
                        print(f"    ✓ Camelot extracted {len(tables)} tables on page {page_num + 1}")
                except Exception as ce:
                    print(f"    ⚠ Camelot failed on page {page_num + 1}: {ce}")
            if not tables:
                tables = page.extract_tables()
            page_months = parse_month_headers(text)
            expected_counts = parse_expected_schoolday_counts(text, start_year)
            
            page_schooldays_before = len(schooldays)
            
            if tables:
                for idx, table in enumerate(tables, start=1):
                    log_table_sample(page_num + 1, idx, table)
                    process_calendar_table(table, schooldays, holidays, start_year, page_months)
            else:
                process_page_text(text, schooldays, holidays, start_year)
            
            print(f"  Page {page_num + 1}: Found {len(tables)} tables")
            
            page_schooldays_added = schooldays[page_schooldays_before:]
            validate_schoolday_counts(page_schooldays_added, expected_counts, page_num + 1)
            
            if not tables and not parse_dates_from_text(text, start_year):
                print(f"    ⚠ No dates parsed from page {page_num + 1}")
    
    return {
        "academic_year": academic_year,
        "schooldays": sorted(schooldays),
        "holidays": sorted(holidays)
    }

def process_calendar_table(table, schooldays, holidays, start_year, page_months):
    """Process a calendar table to extract dates and tag holidays."""
    # Look for calendar grid pattern (M T W T F S S or similar)
    is_calendar_grid = any(
        row and any(cell and str(cell).strip().upper() in ('M', 'T', 'W', 'F', 'S') for cell in row)
        for row in table
    )
    
    if is_calendar_grid:
        process_calendar_grid(table, schooldays, holidays, start_year, page_months)
        return
    
    # Otherwise parse as individual cells
    month_by_col = {}
    for row in table:
        for col_idx, cell in enumerate(row):
            month = detect_month(cell or "")
            if month:
                month_by_col[col_idx] = month
    
    max_cols = max((len(r) for r in table if r), default=0)
    if not month_by_col and page_months and max_cols and max_cols % 7 == 0:
        months_needed = max_cols // 7
        months_seq = page_months[:months_needed]
        for col_idx in range(max_cols):
            month_by_col[col_idx] = months_seq[col_idx // 7]
    
    if month_by_col:
        mapped = ", ".join([f"col {c+1}->{m}" for c, m in sorted(month_by_col.items())])
        print(f"      month map: {mapped}")

    for row in table:
        for col_idx, cell in enumerate(row):
            if not cell:
                continue
            text = str(cell)
            is_holiday = is_holiday_cell(text)
            dates = parse_dates_from_text(text, start_year)
            if not dates and col_idx in month_by_col:
                days = extract_day_numbers(text)
                dates = [to_iso(d, month_by_col[col_idx], start_year) for d in days]
            target = holidays if is_holiday else schooldays
            target.extend(dates)

def process_calendar_grid(table, schooldays, holidays, start_year, page_months):
    """Process a standard calendar grid (M T W T F S S layout)."""
    # Find month headers in preceding rows
    detected_months = []
    for row in table:
        for cell in row:
            if cell:
                month = detect_month(str(cell))
                if month:
                    detected_months.append(month)
    
    if not detected_months and page_months:
        detected_months = page_months[:1]
    
    if not detected_months:
        print(f"      ⚠ Calendar grid without month context")
        return
    
    current_month = detected_months[0]
    year = normalize_year(current_month, start_year)
    _, days_in_month = monthrange(year, current_month)
    
    # Extract all numbers from grid
    all_days = set()
    for row in table:
        for cell in row:
            if cell:
                days = extract_day_numbers(str(cell))
                all_days.update(days)
    
    # Generate all weekday dates for the month
    for day in range(1, days_in_month + 1):
        if day in all_days:
            dt = date(year, current_month, day)
            if dt.weekday() <= 4:  # Monday=0 to Friday=4
                schooldays.append(dt.isoformat())
    
    print(f"      → Extracted {len([d for d in schooldays if d.startswith(f'{year}-{current_month:02d}')])} weekdays for month {current_month}")

def process_page_text(text, schooldays, holidays, start_year):
    """Fallback parser when no tables are detected."""
    is_holiday = is_holiday_cell(text)
    dates = parse_dates_from_text(text, start_year)
    target = holidays if is_holiday else schooldays
    target.extend(dates)

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

HOLIDAY_KEYWORDS = (
    "holiday", "half term", "bank holiday", "easter", "summer", "christmas",
    "inset", "training day", "closure"
)

def is_holiday_cell(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in HOLIDAY_KEYWORDS)

def normalize_year(month: int, start_year: int) -> int:
    """Academic year starts in Sep."""
    return start_year if month >= 9 else start_year + 1

def to_iso(day: int, month: int, start_year: int) -> str:
    year = normalize_year(month, start_year)
    return date(year, month, day).isoformat()

def parse_dates_from_text(text: str, start_year: int):
    """Extract single dates and ranges from arbitrary text."""
    results = []

    # Ranges like "2-6 Sep" or "2 - 6 September"
    range_pattern = r"(\d{1,2})\s*-\s*(\d{1,2})\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    for start_day, end_day, month_str in re.findall(range_pattern, text, flags=re.IGNORECASE):
        month = MONTH_MAP[month_str.lower()[:3]]
        for d in range(int(start_day), int(end_day) + 1):
            results.append(to_iso(d, month, start_year))

    # Single dates like "2 Sep" or "02/09/2025"
    single_pattern = r"(\d{1,2})\s*(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    for day, month_str in re.findall(single_pattern, text, flags=re.IGNORECASE):
        month = MONTH_MAP[month_str.lower()[:3]]
        results.append(to_iso(int(day), month, start_year))

    # Numeric dates like 02/09/2025 or 2/9/25
    numeric_pattern = r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?"
    for day, month, year_part in re.findall(numeric_pattern, text):
        month = int(month)
        day = int(day)
        if year_part:
            year = int(year_part)
            if year < 100:
                year += 2000
            results.append(date(year, month, day).isoformat())
        else:
            results.append(to_iso(day, month, start_year))

    return results

def detect_month(text: str):
    """Return month number if a month name is present."""
    if not text:
        return None
    lower = text.lower()
    for key, month in MONTH_MAP.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return month
    return None

def extract_day_numbers(text: str):
    """Return list of day numbers from text (handles multi-number cells)."""
    return [int(n) for n in re.findall(r"\b(\d{1,2})\b", str(text))]
    
def log_table_sample(page_number, table_index, table):
    """Print a short summary of a detected table for debugging."""
    rows = len(table)
    cols = max((len(r) for r in table if r), default=0)
    preview_rows = []
    for r in table[:3]:
        preview_rows.append(" | ".join([str(c).strip().replace("\n", " ") if c else "" for c in r[:6]]))
    print(f"    Table {table_index} (page {page_number}): {rows} rows x {cols} cols")
    for line in preview_rows:
        print(f"      • {line}")

def parse_month_headers(text: str):
    """Return list of months (numbers) in the order they appear in page text."""
    if not text:
        return []
    months = []
    pattern = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        month_word = match.group(1)
        months.append(MONTH_MAP[month_word.lower()[:3]])
    return months

def parse_expected_schoolday_counts(text: str, start_year: int):
    """Extract expected schoolday counts per month from headers like 'September 2025 (22 days)'."""
    counts = {}
    pattern = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\s+\((\d+)\s+days?\)"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        month_word, year_str, count_str = match.groups()
        month = MONTH_MAP[month_word.lower()[:3]]
        year = int(year_str)
        key = f"{year}-{month:02d}"
        counts[key] = int(count_str)
    return counts

def validate_schoolday_counts(schooldays_list, expected_counts, page_num):
    """Compare extracted schooldays against expected counts per month."""
    if not expected_counts:
        return
    
    actual_counts = defaultdict(int)
    for iso_date in schooldays_list:
        month_key = iso_date[:7]
        actual_counts[month_key] += 1
    
    for month_key, expected in expected_counts.items():
        actual = actual_counts.get(month_key, 0)
        year, month = month_key.split("-")
        month_names = [k for k, v in MONTH_MAP.items() if v == int(month) and len(k) > 3]
        month_name = month_names[0].title() if month_names else f"Month {month}"
        if actual != expected:
            print(f"    ⚠ {month_name} {year}: expected {expected} days, got {actual}")
        else:
            print(f"    ✓ {month_name} {year}: {actual} days (correct)")

def extract_holiday_dates(text: str, start_year: int, holidays: list):
    """Extract specific holiday dates mentioned in footer text."""
    # Look for patterns like "13 August 2026" or "20 August 2026"
    pattern = r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3))
        month = MONTH_MAP[month_name.lower()[:3]]
        try:
            dt = date(year, month, day)
            holidays.append(dt.isoformat())
        except ValueError:
            pass

def extract_exam_results_days(text: str, start_year: int, exam_results_days: list):
    """Extract exam results days from footer text."""
    # Look for patterns like "A Level -13 August 2026" or "GCSE – 20 August 2026"
    pattern = r"(?:A Level|GCSE)\s*[-–]\s*(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3))
        month = MONTH_MAP[month_name.lower()[:3]]
        try:
            dt = date(year, month, day)
            exam_results_days.append(dt.isoformat())
        except ValueError:
            pass

def main():
    print("UTC Sheffield Term Dates Extractor\n")
    
    if not HAS_PYMUPDF:
        print("⚠ PyMuPDF not installed. Install with: pip install PyMuPDF")
        print("  Using fallback method (less accurate)\n")
    
    # Download PDFs
    pdf_files = {}
    for year, url in PDF_URLS.items():
        pdf_file = download_pdf(url, year)
        if pdf_file:
            pdf_files[year] = pdf_file
    
    if not pdf_files:
        print("✗ No PDFs downloaded successfully")
        return
    
    print("\n" + "="*50 + "\n")
    
    # Extract schooldays from each PDF
    all_data = {
        "last_updated": datetime.now().isoformat(),
        "academic_years": []
    }
    
    for year, pdf_path in pdf_files.items():
        data = extract_schooldays_from_pdf(pdf_path, year)
        all_data["academic_years"].append(data)
        
        # Analyze overlaps and gaps
        print(f"\n  Analysis for {year}:")
        schooldays_set = set(data["schooldays"])
        holidays_set = set(data["holidays"])
        exam_results_set = set(data.get("exam_results_days", []))
        
        if exam_results_set:
            print(f"    📅 Exam results days: {len(exam_results_set)}")
            for d in sorted(exam_results_set):
                print(f"      - {d}")
        
        # Check for overlaps
        overlap = schooldays_set & holidays_set
        if overlap:
            print(f"    ⚠ OVERLAP: {len(overlap)} dates in BOTH schooldays and holidays:")
            for d in sorted(overlap)[:10]:
                print(f"      - {d}")
            if len(overlap) > 10:
                print(f"      ... and {len(overlap) - 10} more")
        else:
            print(f"    ✓ No overlaps between schooldays and holidays")
        
        # Generate all weekdays in the academic year range
        if schooldays_set or holidays_set:
            all_dates = sorted(schooldays_set | holidays_set)
            if all_dates:
                start_date = date.fromisoformat(all_dates[0])
                end_date = date.fromisoformat(all_dates[-1])
                
                expected_weekdays = set()
                current = start_date
                while current <= end_date:
                    if current.weekday() <= 4:  # Mon-Fri
                        expected_weekdays.add(current.isoformat())
                    current = current + timedelta(days=1)
                
                # Find missing weekdays
                all_extracted = schooldays_set | holidays_set
                missing = expected_weekdays - all_extracted
                
                if missing:
                    print(f"    ⚠ MISSING: {len(missing)} weekdays not in either list:")
                    for d in sorted(missing)[:10]:
                        print(f"      - {d}")
                    if len(missing) > 10:
                        print(f"      ... and {len(missing) - 10} more")
                else:
                    print(f"    ✓ All weekdays accounted for between {start_date} and {end_date}")
                
                total_weekdays = len(expected_weekdays)
                coverage = len(all_extracted) / total_weekdays * 100 if total_weekdays > 0 else 0
                print(f"    Coverage: {len(all_extracted)}/{total_weekdays} weekdays ({coverage:.1f}%)")
    
    # Write to JSON file
    output_file = "schooldays.json"
    with open(output_file, 'w') as f:
        json.dump(all_data, f, indent=2)
    
    print(f"\n✓ Schooldays extracted to {output_file}")
    
    # Calculate totals - no dedup needed
    total_schooldays = sum(len(y['schooldays']) for y in all_data['academic_years'])
    total_holidays = sum(len(y['holidays']) for y in all_data['academic_years'])
    total_exam_days = sum(len(y.get('exam_results_days', [])) for y in all_data['academic_years'])
    total_teaching_days = total_schooldays
    total_weekdays = total_schooldays + total_holidays
    
    # Calculate weekends
    total_weekends = 0
    for year_data in all_data['academic_years']:
        all_dates = sorted(set(year_data['schooldays']) | set(year_data['holidays']))
        if all_dates:
            start_date = date.fromisoformat(all_dates[0])
            end_date = date.fromisoformat(all_dates[-1])
            current = start_date
            while current <= end_date:
                if current.weekday() > 4:  # Saturday=5, Sunday=6
                    total_weekends += 1
                current = current + timedelta(days=1)
    
    print(f"\n  📊 Summary:")
    print(f"    Teaching days (schooldays): {total_teaching_days}")
    print(f"    Holidays/closures: {total_holidays}")
    print(f"    Exam results days: {total_exam_days}")
    print(f"    Total weekdays (Mon-Fri): {total_weekdays}")
    print(f"    Total weekends (Sat-Sun): {total_weekends}")
    print(f"    Grand total (all days): {total_weekdays + total_weekends}")

if __name__ == "__main__":
    main()
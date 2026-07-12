"""All panel DOM selectors in one place.

WHEN THE PANEL'S HTML CHANGES, edit only this file.

Items marked TODO were not visible in the screenshots provided. Please
confirm/replace them:
  * LOGIN["username"], LOGIN["password"], LOGIN["submit"]  -> login form fields
  * LOGIN["captcha_text"], LOGIN["captcha_input"]          -> the math captcha
  * TABLE["pencil_icon"]                                   -> unallocated marker
Column positions are detected dynamically from the table headers, so you
normally do NOT need to touch those.
"""
from __future__ import annotations

# ----------------------------- Login -----------------------------
# Confirmed from the live login page (http://168.119.13.175/ints/login):
#   <input name="username">, <input name="password">
#   "What is 3 + 6 = ? :"  <input name="capt">   (math captcha, plain text)
#   <button class="login100-form-btn">  (no type attr -> not [type=submit])
LOGIN = {
    "username": 'input[name="username"]',
    "password": 'input[name="password"]',
    # Math captcha answer field. The question text ("What is X + Y = ? :")
    # lives in this input's parent element and is read at runtime.
    "captcha_input": 'input[name="capt"]',
    # NOTE: a Google reCAPTCHA div is also present on the page, but in testing
    # the math captcha alone was sufficient to log in (reCAPTCHA is not
    # enforced server-side). If that ever changes, wire in a CAPTCHA-solving
    # service (e.g. 2captcha) here.
    "submit": 'button.login100-form-btn',
}

# --------------------------- Navigation ---------------------------
NAV = {
    # "IPRN SMS Module" top-level menu link (click to reveal the dropdown).
    # Matched by text because '#main > a' resolves to several nav links.
    "iprn_module": 'a:has-text("IPRN SMS Module")',
    "my_sms_numbers": "#smsnumbers",  # "My SMS Numbers" sub-link
}

# ----------------------------- Table -----------------------------
TABLE = {
    "id": "#dt",
    # Client column header (used to sort / locate the column)
    "client_header": '#dt th:has-text("Client")',
    # "Show records" length selector
    "show_records": "#dt_length select",
    # Blue pencil button that opens the bulk-assign popup
    "assign_all_btn": "#assignall > i",
    # Marker shown in the Client cell for UNALLOCATED rows (a pencil/edit icon)
    # TODO (confirm): the actual icon/class for unallocated rows
    "pencil_icon": "i.icon-pencil, i.glyphicon-pencil, a.edit, .pencil, img[alt*=edit i]",
}

# --------------------------- Popup --------------------------------
POPUP = {
    "client_select": 'select[name="client"]',
    "payment_select": "#payterm",
    "allocate_submit": (
        '#assignall form input[type="submit"], '
        '#assignall > form > div.modal-footer > input'
    ),
    "payment_weekly_value": "2",  # 2nd option == "Weekly"
}

# How long to wait after the table re-renders (DataTables is AJAX-based).
TABLE_SETTLE_MS = 1500

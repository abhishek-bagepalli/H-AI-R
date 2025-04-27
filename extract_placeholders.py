import re

def extract_placeholders(email_text: str) -> dict:
    placeholders = {}

    # 1. Extract employee name from greeting first
    name_match = re.search(r"Hi\s+([A-Z][a-z]+)", email_text) or \
                 re.search(r"Hello\s+([A-Z][a-z]+)", email_text) or \
                 re.search(r"Dear\s+([A-Z][a-z]+)", email_text)

    if not name_match:
        signature_match = re.search(r"(Thanks|Regards|Best|Sincerely)[,\s]*(?:-|—)?\s*([A-Z][a-z]+\s?[A-Z]?[a-z]*)", email_text, re.IGNORECASE)
        if signature_match:
            placeholders["employee_name"] = signature_match.group(2).strip()
        else:
            placeholders["employee_name"] = "Employee"
    else:
        placeholders["employee_name"] = name_match.group(1)

    # 2. Extract leave dates
    date_matches = re.findall(r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4}|\w+\s+\d{1,2}(?:st|nd|rd|th)?(?:,)?\s+\d{4})\b", email_text)
    if date_matches:
        placeholders["leave_dates"] = " to ".join(date_matches) if len(date_matches) >= 2 else date_matches[0]
    else:
        placeholders["leave_dates"] = "the requested dates"

    # 3. Extract number of days
    num_days_match = re.search(r"(\d+)\s+(?:days|day)", email_text.lower())
    if num_days_match:
        placeholders["number_of_days"] = num_days_match.group(1)
    else:
        placeholders["number_of_days"] = "N/A"

    # 4. Other fixed fields
    placeholders["company_name"] = "Company"
    placeholders["list_of_open_roles"] = "Software Engineer, Data Analyst"
    placeholders["careers_portal_link"] = "https://careers.company.com"
    placeholders["submission_deadline"] = "May 31, 2025"
    placeholders["orientation_date"] = "June 10, 2025"
    placeholders["hr_contact_name"] = "Jane Doe"
    placeholders["hr_contact_email"] = "onboarding@company.com"

    # 5. VERY IMPORTANT DEFAULT
    placeholders["approved/denied"] = "approved"

    if "employee_name" in placeholders:
        placeholders["applicant_name"] = placeholders["employee_name"]
    else:
        placeholders["applicant_name"] = "Applicant"
    return placeholders

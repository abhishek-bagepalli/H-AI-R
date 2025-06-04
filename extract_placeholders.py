import re

def extract_placeholders(email_text: str) -> dict:
    """
    Extract placeholders from email text for use in response templates.
    Args:
        email_text: The content of the email to extract placeholders from
    Returns:
        Dictionary of placeholders and their values
    """
    placeholders = {}

    # Set default name first
    placeholders["employee_name"] = "Employee"
    placeholders["applicant_name"] = "Applicant"

    # 1. Extract employee name from greeting first
    name_match = re.search(r"Hi\s+([A-Z][a-z]+)", email_text) or \
                 re.search(r"Hello\s+([A-Z][a-z]+)", email_text) or \
                 re.search(r"Dear\s+([A-Z][a-z]+)", email_text)

    if name_match:
        name = name_match.group(1)
        placeholders["employee_name"] = name
        placeholders["applicant_name"] = name
    else:
        signature_match = re.search(r"(Thanks|Regards|Best|Sincerely)[,\s]*(?:-|—)?\s*([A-Z][a-z]+\s?[A-Z]?[a-z]*)", email_text, re.IGNORECASE)
        if signature_match:
            name = signature_match.group(2).strip()
            placeholders["employee_name"] = name
            placeholders["applicant_name"] = name

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

    return placeholders 
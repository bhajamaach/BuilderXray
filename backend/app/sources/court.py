"""Official eCourts search hand-off.

Party-name case searches require jurisdiction/year selection and a CAPTCHA, so
the app does not claim an automated court search was performed.
"""
ECOURTS_URL = 'https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus%2Findex'
ECOURTS_REASON = (
    'eCourts requires a court jurisdiction and registration year, then a CAPTCHA for party-name searches. '
    'BuilderXray cannot complete that official search automatically. Open eCourts to check manually.'
)

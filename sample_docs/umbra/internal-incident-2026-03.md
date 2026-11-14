# INTERNAL - Incident Postmortem INC-2291 (March 2026)

Confidential: for Umbra Health staff only.

On 14 March 2026 a misconfigured reminder job sent duplicate SMS reminders to 1,842 patients of the Riverside clinic group.
No patient health information was exposed. Root cause: a retry loop in the notification worker ignored the idempotency key.

Remediation: the worker now enforces idempotency keys, and an alert fires when more than 500 SMS are sent per clinic per hour.
Riverside was credited $4,200 for the SMS charges. The account manager is Dana Whitfield.

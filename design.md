# Care Plan Generation System Design Document

## 1. Project Overview

### Objective

Build a web application for CVS healthcare staff to automatically generate patient care plans using structured patient information and clinical records. The system reduces the manual effort required by pharmacists while ensuring compliance with Medicare and pharmaceutical reporting requirements.

---

## 2. Users

### Primary Users

CVS healthcare workers (Medical Assistants / Pharmacists)

Patients do not interact with this system.

### Workflow

1. Healthcare worker enters patient and order information.
2. System validates all input data.
3. System checks for duplicate patients, orders, and providers.
4. If validation succeeds, the system generates a care plan using an LLM.
5. User reviews and downloads the generated care plan.
6. The care plan is printed and provided to the patient.
7. Reporting data can be exported for pharmaceutical reporting.

---

## 3. Care Plan

### Generation Unit

One care plan is generated for one medication order.

If a patient has multiple medication orders, each order generates its own care plan.

### Required Sections

Every generated care plan must include:

* Problem List
* Goals
* Pharmacist Interventions
* Monitoring Plan

---

## 4. Functional Requirements

### Patient Information

The system shall accept the following information:

* Patient First Name
* Patient Last Name
* Patient DOB
* MRN
* Primary Diagnosis (ICD-10)
* Additional Diagnoses
* Medication Name
* Medication History
* Referring Provider
* Provider NPI
* Patient Clinical Record (Text or PDF)

---

### Validation

All user inputs must be validated before submission.

Validation includes:

* Required fields
* MRN format
* NPI format
* ICD-10 format
* File validation (if PDF uploaded)

---

### Duplicate Detection

#### Order Duplicate Rules

| Condition                                      | Result  | Action            |
| ---------------------------------------------- | ------- | ----------------- |
| Same Patient + Same Medication + Same Day      | Error   | Block submission  |
| Same Patient + Same Medication + Different Day | Warning | User may continue |

---

#### Patient Duplicate Rules

| Condition                           | Result  | Action            |
| ----------------------------------- | ------- | ----------------- |
| Same MRN with different Name or DOB | Warning | User may continue |
| Same Name + DOB with different MRN  | Warning | User may continue |

---

#### Provider Validation

| Condition                             | Result | Action           |
| ------------------------------------- | ------ | ---------------- |
| Same NPI with different Provider Name | Error  | Block submission |

NPI is treated as the unique identifier for providers.

---

## 5. Warning vs Error

### Error

Errors prevent submission.

Examples:

* Duplicate order submitted on the same day
* Provider NPI matches an existing provider but the provider name is different
* Invalid required fields

---

### Warning

Warnings notify the user but allow the workflow to continue after confirmation.

Examples:

* Possible duplicate patient
* Same medication ordered again on a different day

---

## 6. Care Plan Generation

After all validation passes:

1. Collect patient information.
2. Collect medication information.
3. Collect diagnoses.
4. Collect clinical records.
5. Send structured information to the LLM.
6. Receive generated care plan.
7. Display the result.
8. Allow the user to download the care plan.

---

## 7. Reporting

The system shall support exporting reporting data required by pharmaceutical partners.

Export capability is required for the initial release.

---

## 8. Download

Users must be able to download the generated care plan for uploading into existing CVS systems and for printing.

---

## 9. Functional Priority

### Phase 1 (Required)

* Patient duplicate detection
* Order duplicate detection
* Provider validation
* Care plan generation
* Care plan download
* Reporting export

All listed features are mandatory for the initial release.

---

## 10. High Level Workflow

```text
Healthcare Worker
        │
        ▼
Fill Web Form
        │
        ▼
Validate Input
        │
        ▼
Duplicate Detection
(Order / Patient / Provider)
        │
        ├──────── Error ───────► Stop Submission
        │
        ├──────── Warning ─────► User Confirms
        │
        ▼
Generate Care Plan (LLM)
        │
        ▼
Display Care Plan
        │
        ▼
Download Care Plan
        │
        ▼
Export Reporting Data
```

---

## 11. Non Functional Requirements

* Input validation for every field
* Data integrity enforced consistently
* Clear and safe error handling
* Modular and maintainable architecture
* Automated test coverage for critical business logic
* End to end deployment with minimal setup

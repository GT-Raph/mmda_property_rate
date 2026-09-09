# MMDA Property Rate Management System

> A multi-role, assembly-scoped property registration, valuation, billing, verification, payment, certificate, notification, and revenue-management platform for Metropolitan, Municipal, and District Assemblies (MMDAs) in Ghana.

![Django](https://img.shields.io/badge/Django-5.2.13-092E20?style=flat-square\&logo=django\&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10.x-3776AB?style=flat-square\&logo=python\&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%20%2F%20Supabase-Primary%20Database-4169E1?style=flat-square\&logo=postgresql\&logoColor=white)
![DRF](https://img.shields.io/badge/Django%20REST%20Framework-3.17.1-A30000?style=flat-square)
![OTP](https://img.shields.io/badge/django--otp-1.7.0-4B32C3?style=flat-square)
![Deployment](https://img.shields.io/badge/Deployment-Render-46E3B7?style=flat-square)
![Status](https://img.shields.io/badge/Status-Active%20Development-orange?style=flat-square)

---

# Overview

**MMDA Property Rate Management System (PRMS)** is a Django-based revenue administration platform designed to manage the property-rate lifecycle for Ghanaian Metropolitan, Municipal, and District Assemblies.

The system combines:

1. **MMDA administration**
2. **Property registration**
3. **Rate-policy configuration**
4. **Annual bill generation**
5. **Field-officer assignment**
6. **Property verification**
7. **Citizen account provisioning**
8. **Property-rate payment**
9. **QR-based certificate verification**
10. **Dispute management**
11. **Persistent user notifications**
12. **Reporting and analytics**

The application is implemented as a modular Django monolith with multiple domain applications sharing the same relational database.

The main runtime request path is:

```text
Admin / Field Officer / Citizen Browser
                 │
                 ▼
        Django URL Dispatcher
                 │
                 ▼
        Authentication Middleware
                 │
        ┌────────┴─────────┐
        │                  │
        ▼                  ▼
Role / Assembly        Password / OTP
Authorization          Security Controls
        │
        ▼
     Django Views
        │
        ├── Properties
        ├── Billing
        ├── Payments
        ├── Field Operations
        ├── Citizens
        ├── Notifications
        └── Reports
        │
        ▼
 Django ORM / Transactions
        │
        ▼
PostgreSQL / Supabase
```

The system is currently server-rendered using Django templates, HTML, CSS, and JavaScript.

Although Django REST Framework is installed, the current repository does **not** expose a substantial public REST API. Most business workflows are implemented through normal Django views.

> **Development status**
>
> The repository contains working implementations for property registration, rate-policy matching, bill generation, role-based access, field assignment, field verification, citizen provisioning, notifications, QR certificate verification, and payment-state tracking.
>
> The current Mobile Money payment workflow is still a development/demo implementation and should not be treated as production payment-gateway integration.

---

# Architecture

## Architectural Style

The application uses a modular Django architecture:

```text
┌──────────────────────────────────────────┐
│                Web Clients               │
│                                          │
│ Admin       Field Officer       Citizen  │
└──────────────────┬───────────────────────┘
                   │
                   │ HTTPS
                   ▼
┌──────────────────────────────────────────┐
│              Django Application          │
│                                          │
│ Authentication                           │
│ Role-Based Authorization                 │
│ Assembly Context                         │
│ Password Enforcement                     │
│ Login Auditing                           │
│ OTP / TOTP                               │
└──────────────────┬───────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     │             │             │
     ▼             ▼             ▼
 Properties      Billing     Field Ops
     │             │             │
     ├─────────────┼─────────────┤
     │             │             │
     ▼             ▼             ▼
 Citizens       Payments    Notifications
     │             │             │
     └─────────────┼─────────────┘
                   │
                   ▼
              Django ORM
                   │
                   ▼
┌──────────────────────────────────────────┐
│          PostgreSQL / Supabase           │
└──────────────────────────────────────────┘
```

---

# Runtime Components

## Admin Portal

The administrative portal provides:

```text
Dashboard
Properties
Billing & Payments
Field Officers
Reports
Assembly Management
Notifications
Settings
```

Administrative access is controlled through `UserProfile.role` and the module-access map defined in:

```text
admins/access.py
```

Major administrative roles include:

```text
sys_admin
revenue_admin
property_officer
payment_officer
billing_officer
report_officer
field_officer
citizen
```

---

# Role Authorization Model

Current module access is defined conceptually as:

```text
System Admin
   └── All administrative modules

Revenue Admin
   └── Dashboard
       Properties
       Billing
       Payments
       Field Operations
       Reports
       Assembly
       Settings

Property Officer
   └── Dashboard
       Properties
       Settings

Payment Officer
   └── Dashboard
       Payments
       Billing
       Settings

Billing Officer
   └── Dashboard
       Billing
       Payments
       Reports
       Settings

Report Officer
   └── Dashboard
       Reports
       Settings

Field Officer
   └── Field Operations
       Properties
       Settings

Citizen
   └── Citizen Portal
       Settings
```

Authorization helpers include:

```python
get_user_role(user)
get_allowed_module_names(user)
get_allowed_modules(user)
can_access(user, module_name)
landing_url_for_user(user)
```

Views use these helpers together with decorators such as:

```python
@module_required(...)
```

to restrict server-side access.

---

# Assembly Access Model

The application is assembly-aware.

Primary assembly data is stored in:

```text
admins.Assembly
```

Important fields include:

```text
name
short_code
assembly_type
region
district
address
contact_phone
contact_email
active_billing_year
is_active
```

Supported assembly types are:

```text
Metropolitan
Municipal
District
```

---

## Staff Assembly Access

Non-system staff normally operate within the assembly assigned to their `UserProfile`.

Conceptually:

```text
Staff Account
     │
     ▼
UserProfile.assembly
     │
     ▼
Assembly-Scoped QuerySets
```

---

## Citizen Multi-Assembly Access

Citizens can own properties in more than one assembly.

`UserProfile` therefore includes:

```text
assembly
allowed_assemblies
```

Citizen-access resolution combines:

```text
Default Assembly
       +
Allowed Assemblies
       +
Assemblies from linked Owner records
```

The profile implements:

```python
accessible_assemblies()
can_access_assembly(...)
```

This prevents the user account from being permanently tied to only one MMDA.

---

# Authentication

The current login routes are separated by user type.

```text
/admin-login/    Staff / administrator login
/owner/login/    Citizen login
/login/          General / legacy portal login
/admin/          Django administration
```

Citizen authentication is phone-oriented.

Internally, Django still authenticates using a username, but the citizen lookup layer resolves the account from the entered phone number.

---

# Citizen Account Provisioning

Citizen accounts can be provisioned automatically during property registration.

The implementation is located in:

```text
properties/utils.py
```

Main function:

```python
link_or_create_citizen_for_owner(...)
```

Processing flow:

```text
Property Owner
     │
     ▼
Already linked?
     │
 ┌───┴────┐
 │        │
Yes       No
 │        │
 ▼        ▼
Reuse   Search Existing Citizen
            │
       ┌────┴────┐
       │         │
     Match     No Match
       │         │
       ▼         ▼
     Link     Create User
                 │
                 ▼
       Generate Temporary Password
                 │
                 ▼
         Link Owner → User
```

---

## Citizen Matching

The matching utility uses normalized values including:

```text
Ghana Card
Email
Phone number
Full name + corroborating phone/email
```

Phone values are normalized to Ghana-style numeric form.

Example:

```text
0241234567
      ↓
233241234567
```

---

## Temporary Password Generation

New citizen passwords use:

```python
secrets.choice(...)
```

with uppercase letters and digits.

Format:

```text
PRMS-XXXXXXXX
```

The generated password is returned once during account creation.

The property-registration workflow displays:

```text
Phone number
Temporary password
```

instead of exposing the internal username.

---

# Forced First-Login Password Change

`UserProfile` contains:

```python
must_change_password
```

New non-superuser profiles are marked for mandatory password replacement.

Enforcement is handled by:

```text
admins.middleware.ForcePasswordChangeMiddleware
```

Conceptually:

```text
Login
  │
  ▼
must_change_password?
  │
 ┌┴────────────┐
 │             │
No            Yes
 │             │
 ▼             ▼
Normal      Password
Access      Change Page
```

Citizens are redirected to their profile password workflow.

Staff are redirected to the password section of administrative settings.

---

# Two-Factor Authentication

The administrative settings application integrates:

```text
django-otp
django_otp.plugins.otp_totp
```

TOTP configuration supports:

```text
Generate TOTP device
Generate QR configuration
Confirm 6-digit token
Disable TOTP
```

This provides optional authenticator-app based second-factor security.

---

# Login Auditing

Authenticated sessions are recorded in:

```text
admins.LoginAudit
```

Tracked information includes:

```text
user
session_key
user_agent
ip_address
device_name
location_label
last_seen
is_active
```

The audit middleware identifies common platforms such as:

```text
Windows
macOS
iPhone
Android
Linux
```

and browser families such as:

```text
Chrome
Firefox
Safari
Edge
```

---

# Property Management

Core models:

```text
properties.Owner
properties.Property
properties.PropertyPhoto
```

---

# Owner Model

Important owner data includes:

```text
assembly
linked_user
full_name
primary_phone
alternate_phone
email
ghana_card_number
postal_address
residential_address
```

An owner may be linked to one Django user through:

```python
linked_user
```

A single citizen user may therefore own properties through multiple `Owner` records.

---

# Property Model

Important fields include:

```text
assembly
owner
property_reference

digital_address
address_line
area_town
suburb
landmark

community_area
latitude
longitude

property_use
building_type
property_class
applied_rate_policy

number_of_floors
number_of_units
year_built
occupancy_status

rateable_value
is_exempt
exemption_reason

registration_source
verification_status
registered_by
last_verified_at
is_active
```

---

# Property Classification

Current property-use choices are:

```text
Residential
Commercial
Industrial
Mixed Use
Institutional
```

Building types include:

```text
Compound House
Self Contained
Detached
Semi Detached
Apartment
Shop
Office
Warehouse
Other
```

Occupancy states include:

```text
Occupied
Vacant
Under Construction
```

---

# Property Reference Generation

Property references are generated automatically.

Format:

```text
<ASSEMBLY_SHORT_CODE>-<10_HEX_CHARACTERS>
```

Example:

```text
AMA-8E72AC9F41
```

Implementation:

```python
f"{assembly.short_code}-{uuid4().hex[:10].upper()}"
```

The property reference is:

```text
Unique
Indexed
Non-editable
```

---

# Verification State Machine

The authoritative property-verification field is:

```python
Property.verification_status
```

Supported values:

```text
pending
under_review
verified
flagged
possible_duplicate
rejected
```

Expected state flow:

```text
Registered
    │
    ▼
Pending
    │
    ├────► Under Review
    │
    ├────► Flagged
    │
    ├────► Possible Duplicate
    │
    ├────► Rejected
    │
    └────► Verified
```

The current system treats `verified` as the condition required before a citizen payment may be applied.

---

# Property Registration Pipeline

The registration workflow is implemented in:

```text
properties/views.py
properties/forms.py
properties/utils.py
billing/models.py
```

Conceptually:

```text
Property Form
     │
     ▼
Validate Owner
     │
     ▼
Validate Property Fields
     │
     ▼
Resolve Assembly Context
     │
     ▼
Resolve Rate Policy
     │
     ▼
Database Transaction
     │
     ├── Save Owner
     ├── Save Property
     ├── Set registered_by
     ├── Set registration_source
     └── Save policy metadata
     │
     ▼
Link/Create Citizen Account
     │
     ▼
Display Credentials if New
```

Registration source is stored as:

```text
admin
field
```

depending on the current role.

---

# Rate Preview Endpoint

The property registration screen includes an internal JSON endpoint:

```http
GET /properties/api/rate-preview/
```

Query inputs include:

```text
property_use
building_type
community_area
rateable_value
```

Example successful logical response:

```json
{
  "policy_name": "Residential Class A 2026",
  "property_class": "Class A",
  "rate_impost": "0.00500",
  "minimum_charge": "150.00",
  "annual_rate": "1250.00",
  "annual_rate_display": "GH₵ 1,250.00",
  "policy_year": 2026,
  "community_area": "Osu",
  "sub_metro": "..."
}
```

This endpoint is currently implemented using Django `JsonResponse`, not DRF serializers/viewsets.

---

# Billing Architecture

Core billing models:

```text
billing.CommunityArea
billing.PropertyClass
billing.RatePolicy
billing.Bill
billing.BillDispute
```

---

# Community Areas

`CommunityArea` is assembly-scoped.

Important attributes:

```text
assembly
sub_metro
name
is_active
```

The database prevents duplicate area definitions for the same:

```text
assembly
sub_metro
name
```

---

# Property Classes

`PropertyClass` groups property areas into administratively configured classes.

Important fields:

```text
assembly
name
covered_areas
is_active
```

Constraint:

```text
UNIQUE(assembly, name)
```

---

# Rate Policy Model

Rate policy fields include:

```text
assembly
policy_name
year
property_use
property_class
covered_areas
building_type
rate_impost
minimum_charge
effective_from
effective_to
status
is_active
notes
```

Policy statuses:

```text
draft
active
inactive
```

---

# Rate-Policy Resolution

Policy matching is implemented through:

```python
RatePolicy.get_applicable_policy(...)
```

The lookup is scoped using:

```text
Assembly
Billing Year
Property Use
Effective Date
Community Area
Building Type
Active Status
```

Matching priority is:

```text
1. Exact community + exact building type
2. Exact community + all building types
3. Global/no-area + exact building type
4. Global/no-area + all building types
```

The newest applicable policy is selected using:

```text
effective_from DESC
created_at DESC
```

---

# Property Rate Calculation

Primary formula:

```text
Principal Rate
    =
Rateable Value
    ×
Rate Impost
```

Implementation:

```python
principal = rateable_value * rate_impost
```

---

## Minimum Charge Rule

If:

```text
computed principal < configured minimum charge
```

then:

```text
principal = minimum charge
```

Final principal values are quantized to:

```text
2 decimal places
```

---

# Bill Architecture

Each property may have only one bill for a billing year.

Database constraint:

```text
UNIQUE(property_record, billing_year)
```

Bill number format:

```text
BILL-<YEAR>-<PROPERTY_REFERENCE>
```

Example:

```text
BILL-2026-AMA-8E72AC9F41
```

---

# Bill Snapshots

The system stores billing snapshots so historical bills do not depend entirely on future policy edits.

Snapshot fields include:

```text
policy_name_snapshot
property_class_snapshot
rateable_value_snapshot
rate_impost_snapshot
```

This provides basic auditability across billing years.

---

# Bill Composition

```text
Principal
    +
Arrears Brought Forward
    +
Penalty
    =
Amount Due
```

Fields:

```text
principal_amount
arrears_brought_forward
penalty_amount
amount_due
amount_paid
```

---

# Bill Status

Supported states:

```text
pending
part_paid
paid
overdue
cancelled
```

Status refresh logic:

```text
amount_paid >= amount_due
        ↓
      Paid

0 < amount_paid < amount_due
        ↓
    Part Paid

amount_paid = 0 and due_date < today
        ↓
     Overdue

otherwise
        ↓
     Pending
```

---

# Automated Bill Generation

Billing services are located in:

```text
billing/services.py
```

Main functions:

```python
get_matching_rate_policy(...)
generate_bill_for_property(...)
generate_missing_bills(...)
```

The annual generation process:

```text
Active Property
      │
      ▼
Existing Bill?
      │
  ┌───┴────┐
  │        │
 Yes       No
  │        │
 Skip      ▼
        Resolve Policy
             │
             ▼
       Calculate Arrears
             │
             ▼
          Save Bill
```

Previous unpaid bill balances are aggregated into:

```text
arrears_brought_forward
```

for the new billing year.

---

# Field Operations

Primary models:

```text
field_operations.EnumerationRecord
field_operations.FieldVisit
field_operations.FieldAssignment
```

---

# Field Assignment

A field officer may receive multiple properties.

Each property is limited to one active assignment at a time.

Database constraint:

```python
UniqueConstraint(
    fields=["property"],
    condition=Q(
        status__in=[
            "assigned",
            "in_progress"
        ]
    )
)
```

This means:

```text
Field Officer A
   ├── Property 1
   ├── Property 2
   ├── Property 3
   └── Property N
```

is valid.

But:

```text
Property 1
   ├── Field Officer A  ← active
   └── Field Officer B  ← active
```

is intentionally prevented.

---

# Assignment Fields

```text
assembly
property
officer
assigned_by
status
priority
due_date
notes
assigned_at
completed_at
```

Statuses:

```text
assigned
in_progress
completed
rejected
cancelled
```

Priorities:

```text
low
medium
high
```

Indexes exist for:

```text
(assembly, status)
(officer, status)
(property, status)
```

---

# Field Verification

The field-verification workflow is assignment-driven.

A field officer may verify only properties with an active assignment belonging to that account.

Conceptually:

```text
Logged-in Field Officer
        │
        ▼
Load Active Assignments
        │
        ▼
Select Assigned Property
        │
        ▼
Submit Verification
        │
        ▼
Lock Assignment + Property
        │
        ▼
Update Property Status
        │
        ├── Create FieldVisit
        ├── Save GPS
        ├── Save Notes
        ├── Save Photos
        └── Update Assignment State
```

---

# Verification Types

Submitted verification types include:

```text
property_verification
site_assessment
payment_verification
dispute_investigation
follow_up
```

The system normalizes these into operational visit types:

```text
verification
follow_up
```

while retaining the original submitted verification value for audit purposes.

Fields:

```text
visit_type
submitted_verification_type
submitted_verification_status
```

This separation makes it possible to preserve user intent while maintaining a smaller operational category set.

---

# Field Visit Audit Data

A `FieldVisit` may contain:

```text
assembly
property
officer
visit_type
submitted_verification_type
submitted_verification_status
payment_status_seen
outcome
amount_outstanding_snapshot
visited_at
next_action_date
latitude
longitude
notes
photo
```

The outstanding amount is snapshotted at visit time.

This means historical field records can retain the amount visible during inspection even if the bill changes later.

---

# GPS Validation

Field verification supports:

```text
latitude
longitude
```

Expected coordinate ranges:

```text
Latitude  -90 to 90
Longitude -180 to 180
```

Coordinates are optional but can be captured during field work.

---

# Verification Photos

Property verification can persist photographs using:

```text
properties.PropertyPhoto
```

Photos are associated with:

```text
property
uploaded_by
caption
```

Uploads are stored under:

```text
media/property_photos/
```

---

# Citizen Portal

Current citizen routes include:

```text
/owner/
/owner/properties/
/owner/bills/
/owner/payments/confirm/
/owner/payments/processing/
/owner/payments/success/
/owner/payments/history/
/owner/profile/
/owner/certificates/
/owner/disputes/submit/
```

Citizens can:

```text
View linked properties
View annual bills
View balances
Pay eligible bills
View payment history
Download certificates
Scan certificate QR codes
Submit disputes
Update profile information
Change password
Manage notification preferences
```

---

# Payment Eligibility

The critical business rule is:

```text
Property must be Active
        AND
Property.verification_status == "verified"
```

Helper:

```python
_property_can_accept_payment(property_obj)
```

Conceptually:

```text
Citizen Selects Bill
        │
        ▼
Property Active?
        │
       No ─────► Reject Payment
        │
       Yes
        │
        ▼
Property Verified?
        │
       No ─────► Reject Payment
        │
       Yes
        │
        ▼
Bill Outstanding?
        │
       No ─────► No Payment Required
        │
       Yes
        │
        ▼
Payment Form
```

The verification check exists in both the citizen workflow and the payment-application service.

---

# Payment Model

Core payment fields:

```text
assembly
property
bill

payer_name
payer_phone
payer_email
property_reference_entered

amount
payment_method
provider
transaction_reference
external_reference

status
reconciliation_status

paid_at
reconciled_at
applied_to_bill
raw_payload
```

Payment methods:

```text
Mobile Money
Card
Bank Transfer
Cash
POS
```

Payment states:

```text
initiated
pending
successful
failed
reversed
```

Reconciliation states:

```text
unmatched
matched
manual_review
```

---

# Payment-to-Bill Application

The reusable settlement service is:

```text
payments/services.py
```

Main function:

```python
apply_payment_to_bill(payment)
```

It uses:

```python
transaction.atomic()
select_for_update()
```

to lock payment and bill records during settlement.

Processing:

```text
Lock Payment
    │
    ▼
Successful?
    │
   No → Stop
    │
    ▼
Linked Bill?
    │
   No → Stop
    │
    ▼
Already Applied?
    │
   Yes → Stop
    │
    ▼
Lock Bill
    │
    ▼
Property Verified + Active?
    │
   No
    │
    ▼
Manual Review
    │
   Yes
    ▼
Increase amount_paid
    │
    ▼
Refresh Bill Status
    │
    ▼
Mark Payment Reconciled
```

This makes payment application idempotent at the application level through:

```text
applied_to_bill
```

---

# Current Mobile Money Limitation

The current citizen-facing Mobile Money flow is **not production gateway integration**.

The existing workflow:

```text
Confirm Payment
      │
      ▼
Processing Page
      │
      ▼
Success View
      │
      ▼
Generate Local Transaction Reference
      │
      ▼
Create Successful Payment
      │
      ▼
Mark Bill Paid
```

The success route currently creates local payment records without a signed callback from a real Mobile Money provider.

Therefore:

> **The current citizen payment flow must be considered a development/demo simulation.**

A production implementation should instead use:

```text
Initiate Provider Transaction
        │
        ▼
Provider Reference
        │
        ▼
Customer Authorization
        │
        ▼
Signed Provider Webhook
        │
        ▼
Verify Signature
        │
        ▼
Verify Amount + Reference
        │
        ▼
Mark Payment Successful
        │
        ▼
Apply Payment to Bill
```

---

# Property Certificates

Certificates are represented by:

```text
citizens.PropertyCertificate
```

Important fields:

```text
property
certificate_uuid
is_active
issued_at
updated_at
```

Relationship:

```text
One Property
     │
     ▼
One PropertyCertificate
```

---

# Certificate Identifier

Certificate numbers are derived as:

```text
<PROPERTY_REFERENCE>-CERT-<YEAR>
```

Example:

```text
AMA-8E72AC9F41-CERT-2026
```

The externally scanned identifier uses:

```python
UUID
```

rather than a sequential database ID.

---

# QR Code Generation

QR generation uses:

```text
qrcode 8.2
```

Route:

```http
GET /owner/certificates/<certificate_uuid>/qr.png
```

The QR contains a verification URL built from:

```text
SITE_PUBLIC_URL
```

or the current request host.

Public verification route:

```http
GET /owner/verify/certificate/<certificate_uuid>/
```

---

# QR Payment Compliance

A scanned certificate currently resolves live billing information.

The server determines:

```text
Billing Year
Payment Status
Amount Due
Amount Paid
Current Balance
Total Outstanding Balance
Last Successful Payment
```

Supported visible payment states include:

```text
Paid
Part Paid
Unpaid
Overdue
No Bill Issued
```

The public certificate view separately reports:

```text
Verified
Pending Verification
Rejected
```

This allows enforcement staff or other authorized operational users to determine both:

```text
Property authenticity/status
        +
Property-rate compliance
```

from the same QR workflow.

---

# Current Certificate Caveat

The repository currently creates a `PropertyCertificate` automatically when a property is created.

Signal:

```text
citizens/signals.py
```

This means certificate-record creation is **not currently verification-gated**.

The QR verification page displays the true verification state, but the existence of a certificate record does not itself prove the property was verified.

If the business rule requires certificates to be issued only after verification, certificate creation should be moved from:

```text
property creation
```

to:

```text
verification transition → verified
```

---

# Notifications

Persistent notifications are stored in:

```text
admins.UserNotification
```

Fields:

```text
user
notification_type
level
title
message
action_url
is_read
read_at
created_at
updated_at
```

Notification levels:

```text
info
success
warning
error
```

Supported categories:

```text
property_verified
property_update
payment
billing
assignment
system
```

---

# Verification Notification

The current automatic notification event is:

```text
Property transitions to verified
```

Signal:

```text
properties/signals.py
```

Processing:

```text
Property pre_save
      │
      ▼
Remember previous status
      │
      ▼
Property post_save
      │
      ▼
New status == verified?
      │
     Yes
      │
      ▼
Was previous status already verified?
      │
     No
      │
      ▼
Resolve Owner.linked_user
      │
      ▼
transaction.on_commit(...)
      │
      ▼
Create UserNotification
```

The citizen is informed that the property is verified and payment is now available.

---

# Notification Centre

Universal authenticated routes include:

```text
/notifications/
/notifications/<id>/read/
/notifications/read-all/
```

Functions:

```python
notifications_center(...)
mark_notification_read(...)
mark_all_notifications_read(...)
```

The system validates notification redirect targets using:

```python
url_has_allowed_host_and_scheme(...)
```

before redirecting after a notification action.

This reduces open-redirect risk.

---

# Modal Message Layer

Global Django messages are rendered using:

```text
templates/shared/message_modal.html
```

The modal layer can display:

```text
Success messages
Warnings
Errors
Informational messages
Citizen login credentials
Unread persistent notifications
```

Field-level validation errors should remain attached to form controls rather than being converted into modal-only feedback.

---

# Dispute Management

Two dispute domains currently exist.

```text
billing.BillDispute
citizens.CitizenDispute
```

Citizen dispute types include:

```text
Rate Assessment
Wrong Owner Details
Wrong Property Type
Duplicate Bill
Payment Issue
Other
```

Citizen dispute states:

```text
submitted
under_review
resolved
rejected
```

Dispute numbers are generated using:

```text
DSP-<YEAR>-<5_DIGIT_SEQUENCE>
```

Example:

```text
DSP-2026-00041
```

Attachments are stored under dynamically generated paths such as:

```text
media/citizens/disputes/<dispute_id>/<uuid>.<ext>
```

---

# Reporting

Administrative reporting supports report types including:

```text
Monthly Revenue
Property Registration
Payment Trends
Outstanding Bills
Dispute Resolution
Field Operations
```

Report execution metadata is recorded in:

```text
admins.ReportRun
```

Fields include:

```text
report_key
generated_by
file_format
rows_count
created_at
```

Excel generation uses:

```text
openpyxl
```

---

# Database Architecture

Primary production database:

```text
PostgreSQL
```

Hosted PostgreSQL can be provided through:

```text
Supabase
```

Connection is configured through:

```env
DATABASE_URL
```

The application uses:

```python
dj_database_url.parse(...)
```

with:

```text
conn_max_age = 600
ssl_require = True
```

when `DATABASE_URL` is configured.

---

# Development Database

If:

```env
DATABASE_URL
```

is not set, Django falls back to:

```text
SQLite
```

using:

```text
db.sqlite3
```

Therefore:

```text
Production
    → PostgreSQL / Supabase

Local fallback
    → SQLite
```

---

# Core Data Model

The central relational structure is approximately:

```text
Assembly
   │
   ├── UserProfile
   ├── Owner
   │     │
   │     └── Property
   │           │
   │           ├── PropertyPhoto
   │           ├── FieldAssignment
   │           ├── FieldVisit
   │           ├── Bill
   │           │     │
   │           │     ├── Payment
   │           │     └── BillDispute
   │           │
   │           ├── PropertyCertificate
   │           └── CitizenDispute
   │
   ├── CommunityArea
   ├── PropertyClass
   ├── RatePolicy
   └── Payments

User
   │
   ├── UserProfile
   ├── LoginAudit
   ├── UserNotification
   ├── Owner records
   ├── Field assignments
   ├── Field visits
   └── Citizen preferences
```

---

# Important Database Constraints

## Assembly

```text
UNIQUE(name)
UNIQUE(short_code)
```

## Property

```text
UNIQUE(property_reference)
```

## Community Area

```text
UNIQUE(
    assembly,
    sub_metro,
    name
)
```

## Property Class

```text
UNIQUE(
    assembly,
    name
)
```

## Bill

```text
UNIQUE(
    property_record,
    billing_year
)
```

## Payment

```text
UNIQUE(transaction_reference)
```

## Field Assignment

```text
One active assignment per property
```

## Certificate

```text
One certificate per property
UNIQUE(certificate_uuid)
```

---

# Technology Stack

| Layer                | Technology                      |
| -------------------- | ------------------------------- |
| Web Framework        | Django 5.2.13                   |
| Language             | Python 3.10.x                   |
| Production Database  | PostgreSQL / Supabase           |
| Development Database | SQLite                          |
| ORM                  | Django ORM                      |
| Server Rendering     | Django Templates                |
| Frontend             | HTML, CSS, JavaScript           |
| Authentication       | Django Auth                     |
| Authorization        | Custom role/module access layer |
| 2FA                  | django-otp / TOTP               |
| JSON Endpoint        | Django JsonResponse             |
| REST Dependency      | Django REST Framework 3.17.1    |
| Filtering Dependency | django-filter 25.2              |
| QR Generation        | qrcode 8.2                      |
| Image Handling       | Pillow 12.2                     |
| Excel Reports        | openpyxl 3.1.5                  |
| PostgreSQL Driver    | psycopg2-binary 2.9.11          |
| Static Files         | WhiteNoise                      |
| Production WSGI      | Gunicorn                        |
| Configuration        | python-dotenv                   |
| Database URL Parsing | dj-database-url                 |

---

# Repository Structure

```text
mmda_property_rate/
│
├── admins/
│   ├── access.py
│   ├── admin.py
│   ├── apps.py
│   ├── assembly_access.py
│   ├── context_processors.py
│   ├── decorators.py
│   ├── forms.py
│   ├── middleware.py
│   ├── migrations/
│   ├── models.py
│   ├── signals.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
│
├── properties/
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── migrations/
│   ├── models.py
│   ├── signals.py
│   ├── tests.py
│   ├── urls.py
│   ├── utils.py
│   └── views.py
│
├── billing/
│   ├── admin.py
│   ├── apps.py
│   ├── migrations/
│   ├── models.py
│   ├── services.py
│   ├── signals.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
│
├── payments/
│   ├── admin.py
│   ├── apps.py
│   ├── migrations/
│   ├── models.py
│   ├── services.py
│   ├── signals.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
│
├── field_operations/
│   ├── admin.py
│   ├── apps.py
│   ├── migrations/
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
│
├── citizens/
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── migrations/
│   ├── models.py
│   ├── signals.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
│
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── templates/
│   ├── admins/
│   ├── citizens/
│   ├── field_operations/
│   ├── properties/
│   ├── billing/
│   ├── registration/
│   └── shared/
│
├── static/
├── staticfiles/
├── media/
├── manage.py
├── requirements.txt
└── README.md
```

---

# Application Routes

## Authentication

| Purpose              | Route           |
| -------------------- | --------------- |
| Staff login          | `/admin-login/` |
| Citizen login        | `/owner/login/` |
| Legacy/general login | `/login/`       |
| Logout               | `/logout/`      |
| Django admin         | `/admin/`       |

---

## Administration

| Purpose   | Route                  |
| --------- | ---------------------- |
| Dashboard | `/dashboard/`          |
| Reports   | `/dashboard/reports/`  |
| Assembly  | `/dashboard/assembly/` |
| Settings  | `/dashboard/settings/` |

---

## Properties

```text
GET  /properties/
GET  /properties/add/
GET  /properties/<id>/
GET  /properties/<id>/edit/
GET  /properties/<id>/document/
GET  /properties/api/rate-preview/
```

---

## Field Operations

```text
GET/POST /field-operations/assign/
GET      /field-operations/
GET      /field-operations/stats/
GET      /field-operations/assignments/
GET/POST /field-operations/verify/
GET/POST /field-operations/verify/<property_id>/
```

---

## Citizen Portal

```text
/owner/
/owner/properties/
/owner/properties/<id>/bills/
/owner/properties/<id>/certificate/

/owner/bills/
/owner/bills/<bill_id>/

/owner/payments/confirm/
/owner/payments/processing/
/owner/payments/success/
/owner/payments/history/

/owner/profile/

/owner/certificates/
/owner/certificates/<uuid>/download/
/owner/certificates/<uuid>/qr.png

/owner/verify/certificate/<uuid>/

/owner/disputes/submit/
```

---

## Notifications

```text
/notifications/
/notifications/<id>/read/
/notifications/read-all/
```

---

# Environment Configuration

Create:

```text
.env
```

in the project root.

Representative configuration:

```env
# --------------------------------------------------
# Django
# --------------------------------------------------

DEBUG=True

SECRET_KEY=replace-with-development-secret

ALLOWED_HOSTS=127.0.0.1,localhost

CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000


# --------------------------------------------------
# PostgreSQL / Supabase
# --------------------------------------------------

DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME


# --------------------------------------------------
# Public certificate URLs
# --------------------------------------------------

SITE_PUBLIC_URL=http://127.0.0.1:8000


# --------------------------------------------------
# Citizen password-reset email
# --------------------------------------------------

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-smtp-username
EMAIL_HOST_PASSWORD=your-smtp-password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=PRMS Support <no-reply@example.com>
```

Production example:

```env
DEBUG=False

SECRET_KEY=<strong-production-secret>

DATABASE_URL=<supabase-postgresql-url>

ALLOWED_HOSTS=your-domain.example

CSRF_TRUSTED_ORIGINS=https://your-domain.example

SITE_PUBLIC_URL=https://your-domain.example

EMAIL_HOST=<production-smtp-host>
EMAIL_PORT=587
EMAIL_HOST_USER=<production-smtp-username>
EMAIL_HOST_PASSWORD=<production-smtp-password>
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=PRMS Support <no-reply@your-domain.example>
```

---

# Local Development

## Requirements

Recommended:

```text
Python 3.10.x
pip
Git
Virtual environment
PostgreSQL or Supabase
```

SQLite may be used for basic local development.

---

# 1. Clone Repository

```powershell
git clone <repository-url>
cd mmda_property_rate
```

---

# 2. Create Virtual Environment

Windows:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

---

# 3. Install Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `pip` reports an encoding problem with the repository's current `requirements.txt`, normalize the file to UTF-8 and rerun the command.

---

# 4. Apply Migrations

```powershell
python manage.py migrate
```

Inspect migration state:

```powershell
python manage.py showmigrations
```

---

# 5. Validate Schema / Models

```powershell
python manage.py check
```

Check for model changes not represented by migrations:

```powershell
python manage.py makemigrations --check --dry-run
```

Expected:

```text
No changes detected
```

---

# 6. Create Administrator

```powershell
python manage.py createsuperuser
```

---

# 7. Start Development Server

```powershell
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/admin-login/
```

Citizen login:

```text
http://127.0.0.1:8000/owner/login/
```

---

# Production Security Configuration

When:

```env
DEBUG=False
```

the current Django settings enable:

```text
SECURE_PROXY_SSL_HEADER
SESSION_COOKIE_SECURE
CSRF_COOKIE_SECURE
SECURE_SSL_REDIRECT
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS
SECURE_HSTS_PRELOAD
SECURE_CONTENT_TYPE_NOSNIFF
X_FRAME_OPTIONS = DENY
SESSION_COOKIE_HTTPONLY
SECURE_REFERRER_POLICY = same-origin
```

---

# CSRF

The application uses Django's normal:

```text
CsrfViewMiddleware
```

State-changing HTML forms should include:

```django
{% csrf_token %}
```

---

# Static Files

Static files use:

```text
WhiteNoise
```

with:

```python
CompressedManifestStaticFilesStorage
```

Production collection:

```powershell
python manage.py collectstatic --noinput
```

---

# Media Storage

Uploaded files currently use:

```python
FileSystemStorage
```

and are written beneath:

```text
media/
```

This includes data such as:

```text
Property photos
Field photos
Dispute attachments
```

> **Deployment warning**
>
> If the application runs on an ephemeral filesystem such as a default Render web service without persistent disk storage, uploaded media may be lost after redeployment/restart.
>
> Production deployment should use either:
>
> ```text
> Persistent Render Disk
> Object Storage
> S3-compatible storage
> Supabase Storage
> ```
>
> or another durable media backend.

---

# Supabase Architecture

Supabase is used as a hosted PostgreSQL provider.

Django communicates through the PostgreSQL connection string.

Conceptually:

```text
Django ORM
    │
    ▼
psycopg2
    │
    ▼
DATABASE_URL
    │
    ▼
Supabase PostgreSQL
```

The current application does not depend on Supabase client-side authentication.

Django remains responsible for:

```text
Authentication
Authorization
Sessions
Business Rules
ORM
Migrations
```

---

# Migrations

Schema changes should be made through Django migrations.

Standard workflow:

```powershell
python manage.py makemigrations
python manage.py migrate
```

Before deployment:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py showmigrations
```

Do not manually alter the Supabase schema when the same table is managed by Django migrations unless the migration state is updated accordingly.

---

# Transaction Boundaries

Critical workflows already use database transactions in several places.

Examples:

```text
Property Registration
Payment Application
Field Verification
Field Assignment
Notification Creation after Verification
```

Where race conditions matter, the application uses:

```python
select_for_update()
```

for record locking.

This should be preserved for:

```text
Bill settlement
Assignment completion
Verification submission
Payment application
```

---

# Security Requirements

## Authorization

Never rely on template visibility alone.

All privileged operations must verify:

```text
Authenticated User
       +
Role Permission
       +
Assembly Permission
       +
Object Ownership / Assignment
```

---

## Payment Security

Never permit:

```text
browser redirect
client-side JavaScript
query-string parameter
```

alone to determine that a payment is successful.

Production payment confirmation must originate from a trusted provider callback.

---

## Citizen Privacy

Do not publicly expose:

```text
Full owner identity
Ghana Card
Private phone numbers
Email addresses
Residential address
Sensitive valuation metadata
```

through the publicly scannable certificate endpoint unless explicitly required by MMDA policy.

---

## Password Security

Temporary passwords must:

```text
Be generated randomly
Be shown only when necessary
Require first-login replacement
Never be hard-coded
```

---

## File Upload Security

Uploaded photos and dispute attachments should be validated for:

```text
File type
Size
Filename
Storage location
Authorization
```

Production implementations should consider malware scanning for arbitrary document uploads.

---

# Testing

The current automated test suite is minimal.

Implemented tests are concentrated in:

```text
admins/tests.py
```

Current coverage includes:

```text
Citizen phone lookup
Citizen assembly-access denial
```

Other application test modules currently contain placeholders.

Run:

```powershell
python manage.py test
```

or:

```powershell
python manage.py test admins
```

---

# Required Test Expansion

Before production deployment, add tests for:

```text
Property registration
Citizen account creation
Random temporary passwords
Forced password changes
Rate policy matching
Minimum charges
Bill generation
Arrears calculation
Property verification
Field assignment authorization
One-active-assignment constraint
Field verification transaction rollback
Unverified payment blocking
Verified payment eligibility
Payment idempotency
Payment reconciliation
QR payment status
Public certificate privacy
Notification generation
Cross-assembly access
Dispute ownership
File upload validation
```

---

# Recommended Security Tests

```text
✓ Citizen cannot access another citizen's property
✓ Field officer cannot verify unassigned property
✓ Field officer cannot access another assembly
✓ Property officer cannot access payment-only module
✓ Unverified property cannot be paid
✓ Manual payment URL does not bypass verification
✓ Duplicate payment cannot be applied twice
✓ Invalid certificate UUID returns 404
✓ Notification cannot be marked read by another user
✓ Notification redirect cannot point to external host
✓ Staff cannot bypass required password change
```

---

# Known Implementation Gaps

The following should be understood before treating the repository as production-ready.

## 1. Citizen Payment Success Is Simulated

The current `/owner/payments/success/` implementation locally creates successful payment records.

It is not currently backed by:

```text
MTN MoMo
Telecel Cash
AirtelTigo Money
Bank API
Card Processor
```

with signed transaction verification.

**Priority: Critical before production.**

---

## 2. Field Officer Property Registry Is Not Fully Assignment-Driven

The dedicated field assignment and verification workflows use:

```text
FieldAssignment
```

However, the current property registry still contains field-officer filtering based on:

```python
registered_by=request.user
```

rather than exclusively using assigned properties.

This creates a consistency gap between:

```text
Field Operations → Assignments
```

and:

```text
Properties → Registry
```

The registry should eventually use the same assignment source of truth.

---

## 3. Certificate Record Is Created Before Verification

A `PropertyCertificate` is currently created when the property itself is created.

If the intended business rule is:

```text
Certificate = evidence of verified property
```

then certificate creation should move to the verification transition.

---

## 4. Limited Automated Tests

Most domain applications currently have empty or placeholder test modules.

Regression risk remains high for:

```text
Billing
Payments
Field Operations
Citizen Workflows
Certificates
Notifications
```

---

## 5. Staff Password-Change Flow Requires Review

`ForcePasswordChangeMiddleware` is present.

However, the staff settings password-change implementation should be verified carefully to ensure:

```text
must_change_password = False
```

is cleared only after a successful password change.

This should have an automated regression test.

---

## 6. Django REST Framework Is Installed but Not a Core API Layer

The repository includes:

```text
djangorestframework
django-filter
```

but current application workflows remain predominantly normal Django views and templates.

Do not document a REST API as implemented unless actual serializers, API views/viewsets, authentication, and routing are added.

---

# Cross-Module Contract

Several domain modules depend directly on one another.

Example:

```text
Property Verification
        │
        ├── Changes Property.verification_status
        │
        ├── Completes FieldAssignment
        │
        ├── Writes FieldVisit
        │
        ├── Generates UserNotification
        │
        └── Enables Citizen Payment
```

Changing verification semantics therefore affects:

```text
properties
field_operations
citizens
payments
notifications
certificates
```

Any change to `Property.verification_status` must be tested across all of these components.

---

# Payment Cross-Module Contract

```text
Bill
  │
  ▼
Payment
  │
  ▼
payments.services.apply_payment_to_bill()
  │
  ├── Property verified?
  ├── Payment successful?
  ├── Already applied?
  └── Bill locked?
  │
  ▼
Bill.amount_paid
  │
  ▼
Bill.refresh_status()
```

Direct modification of:

```text
Bill.amount_paid
```

outside the settlement path should be minimized.

---

# Notification Cross-Module Contract

```text
Property Save
      │
      ▼
properties.signals
      │
      ▼
UserNotification
      │
      ▼
Global Context Processor
      │
      ├── Modal
      └── Notification Centre
```

The signal runs notification creation using:

```python
transaction.on_commit(...)
```

which avoids displaying a verification notification if the outer database transaction fails.

---

# Performance Considerations

Current performance-sensitive areas include:

```text
Large property registries
Annual bill generation
Dashboard aggregations
Outstanding balance aggregation
Field assignment lists
Notification counts
Payment history
Report generation
```

Potential optimizations include:

```text
Pagination
select_related
prefetch_related
Database indexes
Bulk bill generation
Background report generation
Cached dashboard aggregates
Asynchronous notifications
```

---

# Database Indexing

The current models already index important lookup dimensions such as:

```text
Property reference
Property use
Building type
Verification status

Bill year + status

Payment transaction reference
Payment status + reconciliation

Field officer + assignment status
Property + assignment status

User + notification read state
```

Future indexing should be driven by measured query plans rather than adding indexes indiscriminately.

---

# Deployment Architecture

Recommended production topology:

```text
                 INTERNET
                    │
                    │ HTTPS
                    ▼
          ┌──────────────────┐
          │ Render / Proxy   │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │ Gunicorn         │
          │ Django PRMS      │
          └───────┬──────────┘
                  │
          ┌───────┴─────────┐
          │                 │
          ▼                 ▼
┌──────────────────┐ ┌─────────────────┐
│ Supabase         │ │ Persistent Media│
│ PostgreSQL       │ │ Storage         │
└──────────────────┘ └─────────────────┘
```

---

# Production Deployment Checklist

```text
DEBUG=False

Strong SECRET_KEY

Production ALLOWED_HOSTS

Correct CSRF_TRUSTED_ORIGINS

Valid DATABASE_URL

SITE_PUBLIC_URL configured

SMTP settings configured and password-reset email tested

Supabase SSL connection validated

collectstatic executed

Persistent media configured

Migration backup completed

python manage.py check --deploy passes

Payment demo flow disabled/replaced

Administrator 2FA enabled

Default credentials removed

Monitoring enabled
```

---

# Backup & Restore

Production backups should include:

```text
PostgreSQL Database
        +
Uploaded Media
```

Database backup alone does not preserve:

```text
Property photos
Field verification photos
Dispute attachments
```

Restore process:

```text
Restore PostgreSQL
      │
      ▼
Restore Media
      │
      ▼
Apply Migrations
      │
      ▼
Check File References
      │
      ▼
Run Django Checks
      │
      ▼
Test Property / Bill / Certificate
```

---

# Logging & Monitoring

Production monitoring should cover:

```text
HTTP 5xx rate
Authentication failures
Permission-denied attempts
Database availability
Slow queries
Property registration failures
Rate-policy matching failures
Payment failures
Payment reconciliation failures
Field verification errors
Upload failures
Certificate scan failures
Notification failures
Disk/media usage
```

---

# Git Ignore

Sensitive/runtime files should remain outside version control.

Recommended:

```gitignore
.env

.venv/
venv/

__pycache__/
*.pyc

db.sqlite3

media/
staticfiles/

*.log

.vscode/
.idea/

.DS_Store
Thumbs.db
```

If media assets are intentionally versioned, adjust selectively.

Adding a path to `.gitignore` does not remove files already tracked.

---

# Coding Standards

## Django

Views should generally follow:

```text
Authenticate
    ↓
Authorize Role
    ↓
Resolve Assembly
    ↓
Scope QuerySet
    ↓
Validate Input
    ↓
Execute Transaction
    ↓
Render / Redirect
```

---

## ORM

Use:

```python
select_related(...)
prefetch_related(...)
```

for known relational access patterns.

Do not use `select_related()` on plain fields.

---

## Transactions

Use:

```python
transaction.atomic()
```

for workflows that modify multiple logically related records.

Use:

```python
select_for_update()
```

when concurrent requests could modify the same financial or workflow record.

---

## Financial Data

Use:

```python
Decimal
```

not binary floating-point values for:

```text
Rateable values
Rate impost calculations
Bills
Penalties
Payments
Balances
```

---

## Secrets

Never hard-code:

```text
SECRET_KEY
Database credentials
Production passwords
API keys
Payment-provider secrets
```

---

# Git Workflow

Check status:

```powershell
git branch --show-current
git status
```

Create a feature branch:

```powershell
git checkout -b feature/short-description
```

Examples:

```text
feature/payment-provider-integration
feature/notification-center
feature/assignment-dashboard

fix/verified-payment-routing
fix/field-verification-transaction
fix/certificate-status

hardening/role-access
hardening/file-upload-validation
hardening/payment-webhook
```

Before committing:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
git status
```

Commit:

```powershell
git add .
git commit -m "Fix concise description"
```

Push:

```powershell
git push -u origin feature/short-description
```

---

# Pull Request Requirements

A pull request should identify:

1. What changed
2. Why it changed
3. User roles affected
4. Assembly-scoping impact
5. Database impact
6. Migration impact
7. Billing impact
8. Payment impact
9. Verification impact
10. Notification impact
11. Security impact
12. Tests performed
13. Deployment impact

Financial changes should additionally identify:

```text
Rate formula changed?
Bill calculation changed?
Payment state changed?
Reconciliation changed?
Historical bill snapshots affected?
```

---

# Current Implementation Scope

## Implemented

```text
✓ Django authentication
✓ Role-based module access
✓ Assembly management
✓ Multi-assembly citizen access
✓ Staff/citizen login separation
✓ Citizen phone login resolution
✓ Automatic citizen account linking
✓ Random temporary credentials
✓ First-login password enforcement
✓ TOTP setup
✓ Login auditing

✓ Property registration
✓ Owner management
✓ Property reference generation
✓ Community areas
✓ Property classes
✓ Rate policies
✓ Rate preview
✓ Property photos

✓ Annual bill generation
✓ Rate impost calculations
✓ Minimum charges
✓ Arrears
✓ Penalties
✓ Bill status tracking
✓ Historical billing snapshots

✓ Field assignments
✓ Multiple properties per officer
✓ One active officer per property
✓ Field verification
✓ Verification audit data
✓ GPS capture
✓ Field photos
✓ Outstanding balance snapshots

✓ Citizen portal
✓ Bill visibility
✓ Payment eligibility gating
✓ Payment history
✓ Disputes
✓ Profile management

✓ QR certificates
✓ Public certificate verification
✓ Live payment compliance status

✓ Persistent notifications
✓ Verification notifications
✓ Notification centre
✓ Modal Django messages

✓ Reports
✓ Excel support
✓ Render-oriented production settings
✓ Supabase/PostgreSQL support
```

---

# Not Production-Complete

```text
Production Mobile Money gateway
Signed payment webhooks
Provider-side transaction verification
Automated SMS delivery
Automated email delivery
Object-storage integration
Comprehensive audit log
Comprehensive automated tests
Malware scanning
Background task queue
Scheduled billing jobs
Scheduled arrears/penalty jobs
Structured application monitoring
Automated database backups
```

---

# Development Priorities

## P0 — Financial Security

```text
Replace simulated payment success
Integrate real payment provider
Verify signed webhooks
Add payment idempotency keys
Test payment replay attacks
Test amount tampering
Test manual URL bypass
```

---

## P1 — Authorization & Workflow Consistency

```text
Make property registry assignment-driven for field officers
Audit all assembly scoping
Test role permissions
Test direct object URL manipulation
Gate certificate issuance if required by policy
Fix and test staff first-login password clearing
```

---

## P2 — Automated Tests

```text
Property tests
Billing tests
Payment tests
Field assignment tests
Field verification tests
Certificate tests
Notification tests
Cross-assembly tests
```

---

## P3 — Reliability & Operations

```text
Persistent media storage
Structured logs
Error monitoring
Database backups
Report-job handling
Notification delivery services
```

---

# Definition of Done

A PRMS change is complete only when applicable items are satisfied.

* [ ] Requirement is implemented
* [ ] Role access is verified
* [ ] Assembly access is preserved
* [ ] Citizen ownership scope is preserved
* [ ] Database constraints remain valid
* [ ] Financial calculations use Decimal
* [ ] Transaction boundaries are reviewed
* [ ] Migrations are reviewed
* [ ] Payment gating remains enforced
* [ ] Verification workflow remains synchronized
* [ ] Notification behavior is verified
* [ ] Certificate behavior is verified
* [ ] Direct URL manipulation is tested
* [ ] Django system checks pass
* [ ] Migration dry-run passes
* [ ] Automated tests pass
* [ ] Manual workflow is tested
* [ ] Production impact is documented
* [ ] README is updated

---

# Collaborator Checklist

## Before Development

* [ ] Read this README
* [ ] Activate virtual environment
* [ ] Confirm current Git branch
* [ ] Run `git status`
* [ ] Run `python manage.py check`
* [ ] Review relevant models
* [ ] Review current migrations
* [ ] Review role/module permissions
* [ ] Review assembly scope
* [ ] Reproduce the reported issue
* [ ] Create a dedicated branch

---

## Before Review

* [ ] Run Django checks
* [ ] Run migration dry-run
* [ ] Run tests
* [ ] Test administrator workflow
* [ ] Test field officer workflow where affected
* [ ] Test citizen workflow where affected
* [ ] Test another assembly where relevant
* [ ] Test direct URLs
* [ ] Test invalid permissions
* [ ] Review database migrations
* [ ] Review transaction handling
* [ ] Review security impact
* [ ] Document new environment variables
* [ ] Update README

---

# Reporting Technical Issues

When reporting an issue, include:

```text
Title:

Environment:
Local / Staging / Production

User role:
System Admin / Revenue Admin / Property Officer /
Billing Officer / Payment Officer / Report Officer /
Field Officer / Citizen

Assembly:

Component:
Admin / Properties / Billing / Payments /
Field Operations / Citizens / Certificates /
Notifications / Reports

Steps to reproduce:
1.
2.
3.

Expected:

Actual:

URL:

HTTP status:

Traceback:

Property reference:

Bill number:

Transaction reference:

Verification status:

Data impact:
[ ] Property
[ ] Owner
[ ] Bill
[ ] Payment
[ ] Assignment
[ ] Certificate
[ ] Notification
[ ] Cross-assembly exposure
[ ] None known
```

Do not include:

```text
Passwords
Temporary passwords
SECRET_KEY
DATABASE_URL
Database passwords
Payment API secrets
Session cookies
CSRF tokens
Private citizen documents
```

---

# Project Status

```text
Django Application             ██████████  Implemented
Role-Based Access              ██████████  Implemented
Assembly Scoping               █████████░  Implemented / needs more tests
Property Registry              ██████████  Implemented
Rate Policy Engine             ██████████  Implemented
Bill Generation                ██████████  Implemented
Field Assignment               ██████████  Implemented
Field Verification             █████████░  Implemented / regression-prone
Citizen Portal                 ██████████  Implemented
Payment Eligibility Gate       ██████████  Implemented
Payment Data Model             ██████████  Implemented
Real Payment Gateway           ██░░░░░░░░  Not implemented
QR Certificates                ██████████  Implemented
QR Payment Compliance          ██████████  Implemented
Notifications                  ██████████  Implemented
TOTP / 2FA                     ████████░░  Implemented
First-Login Password Control   ████████░░  Implemented / needs tests
Reports                        █████████░  Implemented
Automated Tests                ██░░░░░░░░  Minimal
Persistent Media Storage       ███░░░░░░░  Deployment dependent
Production Observability       ██░░░░░░░░  Future hardening
```

> These indicators describe implementation presence in the repository. They are not a certification of production readiness.

---

# Documentation Rule

This README should be updated whenever the project changes:

```text
Role permissions
Assembly behavior
Verification status logic
Rate formulas
Rate-policy matching
Bill generation
Payment eligibility
Payment integration
Notification workflow
Certificate behavior
Database models
Migrations
Environment variables
Deployment configuration
```

When documentation conflicts with source code, the current:

```text
models.py
services.py
views.py
middleware.py
signals.py
urls.py
migrations/
tests.py
```

should be treated as the authoritative implementation.

---

# License

No authoritative project license file was identified in the reviewed MMDA PRMS source used to prepare this README.

Add a `LICENSE` file before describing the repository as MIT, Apache, GPL, or another licensed distribution.

---

<p align="center">
  <strong>MMDA Property Rate Management System</strong>
</p>

<p align="center">
  Property Registry · Rate Policies · Billing · Field Verification · Citizen Payments · QR Compliance
</p>

<p align="center">
  <sub>Django · PostgreSQL / Supabase · Role-Based Access · Assembly-Scoped Revenue Administration</sub>
</p>

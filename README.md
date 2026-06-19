# MMDA Property Rate Management System (PRMS)

A centralized web-based Property Rate Management System for Metropolitan, Municipal, and District Assemblies (MMDAs) in Ghana.

---

## 1. Project Overview

The **MMDA Property Rate Management System (PRMS)** is designed to digitize and streamline the full property rate lifecycle across assembly administration, field operations, citizen access, billing, and payment tracking.

The system brings together the following processes into a single platform:

* Property registration and record management
* Rate policy application and annual rate calculation
* Bill generation and payment tracking
* Field verification and enforcement support
* Citizen account linking and self-service access
* Dispute submission and review
* Reporting and administrative oversight

The project addresses common local-government challenges such as:

* incomplete property databases
* manual or fragmented billing processes
* inconsistent ownership records
* difficult payment reconciliation
* limited citizen access to bills and receipts
* lack of real-time enforcement verification tools

---

## 2. Core Objectives

The main goals of the system are to:

* improve the quality and completeness of property data
* automate annual property rate calculations
* reduce billing and reconciliation errors
* support mobile-assisted field registration and verification
* give citizens secure access to their property records and bills
* improve transparency and accountability in internally generated revenue (IGR)

---

## 3. User Roles

The platform supports multiple user types with role-based access.

### 3.1 System / Revenue Administrators

Administrators manage the core operations of the system, including:

* assemblies
* property records
* rate policies
* billing
* payments
* disputes
* reporting
* user setup and access control

### 3.2 Field Officers

Field officers use the platform to:

* register newly discovered properties
* work with location-related property data
* verify assigned or accessible records
* support enforcement operations
* see records relevant to their login and workflow

### 3.3 Citizens / Property Owners

Citizens use the portal to:

* link their properties
* view property records
* view bills
* monitor payment status
* download receipts or documents
* submit disputes when information is incorrect

---

## 4. Functional Modules

## 4.1 Property Management Module

Handles creation, storage, update, and retrieval of property records.

Typical data points include:

* owner details
* assembly
* community / area
* property use
* building type
* property class
* rateable value
* address and location details
* latitude / longitude
* verification status
* registration source
* linked policy snapshot

## 4.2 Billing Module

Responsible for turning property records into chargeable annual bills.

It supports:

* rate policy matching
* rate impost application
* minimum charge enforcement
* arrears
* penalties
* annual bill generation
* bill snapshots for auditability

## 4.3 Payment Module

Tracks payment against generated bills and supports:

* amount due
* amount paid
* balance
* pending / part-paid / paid / overdue states
* payment-to-bill linkage
* payment visibility by role and ownership context

## 4.4 Citizen Portal Module

Allows property owners to securely interact with their records and bills.

Typical activities include:

* account access
* property linking
* viewing bills
* downloading records
* updating limited profile information
* submitting billing-related disputes

## 4.5 Field Operations Module

Supports mobile or lightweight workflows for field staff.

Typical uses include:

* property enumeration
* property registration
* verification support
* enforcement follow-up
* record review during field visits

## 4.6 Dispute Management Module

Allows issues to be raised and tracked.

Typical dispute categories include:

* wrong owner
* wrong classification
* wrong rateable value
* payment not reflected
* duplicate property
* other administrative issues

## 4.7 Reporting and Analytics Module

Provides management visibility into:

* registered properties
* issued bills
* payments collected
* outstanding balances
* operational activity
* enforcement and dispute patterns

---

## 5. Business Workflow

A standard high-level workflow is:

1. A property is registered by an admin or field officer.
2. A unique property reference is generated.
3. The system determines the applicable active rate policy.
4. The annual property rate is computed.
5. A bill is generated for the billing year.
6. The citizen account is linked or created.
7. The property owner views the record and bill through the portal.
8. Payments are recorded and reflected in the billing status.
9. Field officers and administrators verify or act on the current status.
10. Disputes are raised and resolved where necessary.

---

## 6. Billing and Rate Logic

The billing engine is policy-driven.

### 6.1 Core Formula

```text
Annual Property Rate = Rateable Value × Rate Impost
```

### 6.2 Minimum Charge Rule

If the computed amount is lower than the configured minimum charge, the minimum charge is used instead.

### 6.3 Policy Matching Inputs

The system is designed to match an applicable policy using factors such as:

* assembly
* billing year
* property use
* community / area
* building type
* policy status
* policy effective dates

### 6.4 Bill Composition

A bill may include:

* principal amount
* arrears brought forward
* penalty amount
* total amount due
* amount paid
* balance

---

## 7. Current Implementation Highlights

The current codebase already includes the following important behaviors:

### 7.1 Property Registration Form Logic

The property creation form supports:

* owner selection or new-owner creation
* structured property fields
* community / area selection
* address and location-related fields
* latitude / longitude fields
* automatic read-only handling for coordinate fields
* validation of rateable value
* automatic rate-policy resolution before final save

### 7.2 Policy Preview and Matching

The property rate preview endpoint validates:

* property use
* building type
* community / area
* rateable value

It then returns:

* policy name
* property class
* rate impost
* minimum charge
* calculated annual rate
* policy year
* matched community / sub-metro

### 7.3 Registry Visibility by Role

The property registry is filtered by:

* active assembly context
* user role
* field officer ownership of records where applicable
* search terms
* property type
* active / pending / inactive status

### 7.4 Automatic Citizen Linking / Creation

When a property is successfully added, the system:

* attempts to find a matching citizen account
* links an existing account if a reliable match exists
* otherwise creates a new citizen account
* stores the account linkage on the owner record

The current helper supports a default temporary password workflow.

---

## 8. Project Structure

A typical project structure is expected to look like this:

```text
mmda_property_rate/
├── admins/
├── billing/
├── citizens/
├── field_operations/
├── payments/
├── properties/
├── templates/
├── static/
├── media/
├── manage.py
└── README.md
```

### App Responsibilities

#### `admins`

Administrative setup, assembly management, preferences, user profiles, high-level dashboards, and access control.

#### `properties`

Owner records, property records, property registration forms, property views, registry, detail/edit/download flows.

#### `billing`

Community areas, rate policies, bill generation logic, bill models, dispute records linked to bills.

#### `payments`

Payment records and bill settlement tracking.

#### `citizens`

Citizen-facing workflows such as profile access, certificates, disputes, bill visibility, and self-service functions.

#### `field_operations`

Enumeration and field visit tracking.

---

## 9. Technology Direction

The project is built around a Django-based web application architecture with a PostgreSQL-backed data layer.

Typical stack assumptions for this project include:

* Python
* Django
* PostgreSQL / Supabase Postgres
* HTML templates
* CSS
* JavaScript
* Django admin
* static/media file handling

Optional or evolving frontend pieces may include:

* map integration for location capture
* icons and branded admin templates
* responsive mobile-focused field officer screens

---

## 10. Environment Setup

## 10.1 Prerequisites

Install and configure:

* Python 3.x
* pip
* virtual environment support
* PostgreSQL database
* Git

## 10.2 Clone the Project

```bash
git clone <your-repository-url>
cd mmda_property_rate
```

## 10.3 Create and Activate a Virtual Environment

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
```

## 10.4 Install Dependencies

```bash
pip install -r requirements.txt
```

## 10.5 Configure Environment Variables

Create a `.env` or set environment variables for values such as:

```env
DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
ALLOWED_HOSTS=127.0.0.1,localhost
```

If you are using Supabase, use the PostgreSQL connection details from the Supabase project settings.

## 10.6 Apply Migrations

```bash
python manage.py migrate
```

## 10.7 Create a Superuser

```bash
python manage.py createsuperuser
```

## 10.8 Run the Development Server

```bash
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/
```

---

## 11. Working with PostgreSQL / Supabase

This project uses PostgreSQL-compatible migrations and works with local Postgres or hosted PostgreSQL such as Supabase.

### Local Postgres

Point `DATABASE_URL` or Django database settings to your local database.

### Supabase

Use the Postgres connection string, not the client-side API URL, for Django database access.

Important notes:

* Django migrations create and update the schema.
* Supabase is used here as a Postgres host, not as a replacement for Django’s auth/business layer.
* If migration history becomes inconsistent, reset only if you are in a development environment and understand the data-loss impact.

---

## 12. Property Registration Flow

When adding a property, the expected flow is:

1. Choose an existing owner or enter a new owner.
2. Enter property classification data such as:

   * property use
   * building type
   * community / area
   * occupancy details
   * address details
   * rateable value
3. Enter or capture location fields:

   * address line
   * area / town
   * suburb
   * digital address
   * landmark
   * latitude
   * longitude
4. The system validates the inputs.
5. The system resolves the matching rate policy.
6. The property is saved with:

   * generated property reference
   * matched policy
   * policy class snapshot
   * registration source
   * registering user
7. The owner is linked to a citizen account or a new one is created.

---

## 13. Property Registry, Detail, Edit, and Download

The registry is intended to act as the operational listing screen for properties.

It typically supports:

* search
* pagination
* status filtering
* property type filtering
* role-aware results
* quick actions

Recommended actions on each property row:

* **View** — open property detail page
* **Edit** — update property details
* **Download** — export a printable or text/PDF representation

If any of these actions are not working in the current UI, check that:

* URLs exist in `properties/urls.py`
* matching views exist in `properties/views.py`
* template action links do not use `href="#"`

---

## 14. Citizen Account Linking and Creation

The owner-to-citizen linking utility attempts to find a unique citizen match using combinations such as:

* full name + phone
* full name + email
* exact full name only when unique

If no safe match exists, it creates a citizen user automatically.

The current logic includes:

* username generation from owner name and phone tail
* profile creation with `citizen` role
* assembly assignment
* phone sync to user profile
* owner-to-user linking

This allows property registration to immediately prepare citizen access without separate manual account setup.

---

## 15. Location and Address Data

The project already includes support for structured location-related fields in property creation:

* address line
* area / town
* suburb
* digital address
* landmark
* latitude
* longitude

This gives the project a good foundation for map-assisted registration, duplicate detection, and field validation workflows.

If map integration is enabled in the property form template, these fields can be auto-populated from typed location data or map interaction.

---

## 16. Field Officer Behavior

The registry view already supports role-based filtering for field officers.

Expected behavior:

* field officers should see only records relevant to their role
* field officers can be limited to properties they registered
* assembly context should also restrict visible data
* field workflows should be simpler and more mobile-friendly than admin workflows

---

## 17. Disputes

The dispute layer is designed to capture citizen or admin-raised issues related to billing and property records.

A dispute record can include:

* bill reference
* issue type
* description
* optional attachment
* status
* admin notes
* reviewed by / reviewed at
* resolution summary

This supports auditability and structured service response.

---

## 18. Common Management Commands

Typical commands used during development:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Useful extras depending on the project state:

```bash
python manage.py collectstatic
python manage.py shell
python manage.py showmigrations
```

---

## 19. Troubleshooting

## 19.1 Migrations Out of Sync

If migrations become inconsistent:

* confirm all app migration files match the current model structure
* check `showmigrations`
* avoid mixing two incompatible schema designs
* reset the dev database only when necessary and only in development

## 19.2 Broken Action Buttons

If View/Edit/Download do not work:

* confirm template links are not `#`
* confirm route names exist
* confirm corresponding views exist
* confirm permissions and role checks are not blocking access

## 19.3 `select_related` Errors

Only use `select_related()` with relational fields such as `ForeignKey` and `OneToOneField`.

Do not use it with plain text fields such as a `CharField` `property_class`.

## 19.4 No Matching Rate Policy

If property save fails with a rate policy error:

* check assembly context
* check active policy status
* check effective date range
* check property use
* check community / area
* check building type
* check billing year

## 19.5 Citizen Account Not Linked

If owner-to-citizen linking fails:

* confirm owner name exists
* confirm phone or email values are stored cleanly
* confirm citizen profiles exist under the correct role and assembly
* review matching logic for duplicates

---

## 20. Security Notes

Recommended security practices:

* do not expose sensitive property-owner data publicly
* restrict role-based actions carefully
* protect admin-only views with decorators and server-side checks
* use secure passwords and password-change flows
* rotate temporary credentials after first login
* validate uploads and dispute attachments
* separate development secrets from production secrets

---

## 21. Suggested Future Enhancements

Recommended next steps for the project:

* PDF export for property records and bills
* proper property detail/edit/download templates and views everywhere
* map-based coordinate capture in property registration
* stronger duplicate-property detection
* SMS / email notifications
* payment gateway integration
* full audit trail for edits
* document generation for bills and certificates
* better dashboard analytics and charts
* more granular group-based permissions
* assembly onboarding tools and seed/import utilities
* CSV/Excel import/export for master data

---

## 22. README Maintenance Notes

Update this README whenever you change:

* app structure
* model relationships
* role logic
* rate policy rules
* environment configuration
* URL names
* templates or admin flows
* citizen onboarding behavior

This README should be treated as the main onboarding document for developers, implementers, and administrators working on the system.

---

## 23. Summary

The MMDA PRMS is a centralized property rate platform aimed at improving:

* property data quality
* billing accuracy
* revenue transparency
* payment visibility
* field verification
* citizen self-service access

It is designed to serve administrators, field officers, and citizens within one coordinated system and provides a solid foundation for a full digital local-government property rate workflow.

# CAMO v0.7.0 Migration & Feature Implementation Plan

## Summary

This document outlines the migration path from CAMO v0.4.2 → v0.7.0 and the implementation of the following features:

- **High Priority:** Auto-save with save indicator, ORCID tracking
- **Medium Priority:** Geographic lookups, study duration calculation
- **Non-urgent:** Remove duplicate credit icons

---

## Part 1: CAMO Schema Migration (v0.4.2 → v0.7.0)

### 1.1 Breaking Changes

#### Slot Renames
- `variable_attribute` → `measured_attribute` (CausalNode)
  - **Impact:** Form rendering, data model, service layer
  - **Files to update:**
    - `apps/annotation/services.py:374` (`_derive_name()` helper)
    - `config/loom_ui.yaml:81` (ontology routing config)

#### Required Slot Changes
- `entity_term` now required on CausalNode (was optional)
  - Loom's schema engine will handle automatically via `schema_view.bind_form_data()`

#### Enum Expansions
- `StateOrChangeQualifierEnum` expanded (6 new values)
  - New: `occurred`, `initiated`, `terminated`, `ongoing`, `interrupted`, `aborted`

#### Removed Slots
- `conditioned_by` (likely migrated to `ecosystem_context`)
- `account_families` (handled by `philosophical_accounts`)

### 1.2 Data Migration Commands

```bash
# 1. Load new schema (must be done first)
python manage.py load_schema config/schema/camo-0.7.0.yaml --activate

# 2. Update existing node data (optional - for v0.4.2 data)
python manage.py shell <<EOF
from apps.annotation.models import Node
from django.db.models import JSONB
Node.objects.update(
    data=jsonb_set(
        data - 'variable_attribute',
        '{measured_attribute}',
        data->'variable_attribute'
    )
)
EOF
```

### 1.3 Configuration Updates

**File: `config/loom_ui.yaml`**
```yaml
# Replace:
ontology_routing:
  variable_attribute: [PATO]
# With:
  measured_attribute: [PATO]

# Remove from globally_hidden_slots:
  - conditioned_by
```

### 1.4 Testing Checklist

- [ ] Node forms render with `measured_attribute`
- [ ] Node creation requires `entity_term`
- [ ] Enum autocomplete accepts new StateOrChangeQualifier values
- [ ] Export validates against CAMO v0.7.0 schema

---

## Part 2: Feature Implementations

### 2.1 Auto-Save with Save Indicator

**Implementation:**
- Backend endpoint: `AutoSaveView` (PATCH to update data field)
- JavaScript: debounce input changes (500ms), show timestamp icon
- Templates: Add `data-save-indicator` elements

**Estimated Files:**
- Create: `apps/annotation/utils.py`
- Modify: `apps/annotation/views.py`, `static/js/annotation-actions.js`
- Modify: `templates/annotation/partials/node_form.html`, `edge_form.html`

### 2.2 ORCID Storage

**Implementation:**
- Add `orcid` field to User model
- Update service layer to include ORCID in annotation data
- Create migration for existing users

**Estimated Files:**
- Create: `apps/accounts/migrations/0002_add_orcid_field.py`
- Modify: `apps/accounts/models.py`, `apps/annotation/services.py`

### 2.3 Geographic Lookups

**Two approaches:**
1. Pre-loaded ontology terms (recommended - no API key needed)
2. GeoNames API (requires API key)

**Implementation:**
- Create `get_geographic_context()` utility function
- Call on node creation, populate `study_country` and `study_state_or_province`

**Estimated Files:**
- Create: `apps/annotation/utils.py`
- Modify: `apps/annotation/services.py`

### 2.4 Study Duration Calculation

**Implementation:**
- Parse `study_period_start` and `study_period_end`
- Calculate months between dates
- Store in `study_duration_months` (computed field)

**Estimated Files:**
- Create: `apps/annotation/utils.py`
- Modify: `apps/annotation/services.py`

### 2.5 Remove Duplicate Credit Icons

**Implementation:**
- Identify all templates with credit icons
- Move to base template footer
- Remove from partial templates

**Estimated Files:**
- Modify: `templates/base.html`, `templates/annotation/partials/*.html`

---

## Questions for User

1. **GeoNames API:** Do you have a username, or use pre-loaded ontology terms?
2. **ORCID Collection:** Add field to user profile or assume entered?
3. **Auto-save Scope:** All fields or only long-form fields?
4. **Study Duration:** Override after auto-calculation or always recompute?
5. **Template Credits:** Should I identify locations or do you have specific templates?

---

## Estimated Timeline

| Task | Estimate |
|------|----------|
| Schema migration + testing | 2-4 hours |
| Auto-save implementation | 4-6 hours |
| ORCID integration | 2-3 hours |
| Geographic lookups | 3-5 hours |
| Study duration calculation | 1-2 hours |
| Template cleanup | 1 hour |
| **Total** | **13-21 hours** |

---

*This document will be updated as implementation progresses.*

# charge-grid-nsw

A data engineering pipeline that integrates Transport for NSW EV charger data with ABS regional spatial boundaries. It augments DC fast chargers via external APIs and stores the final spatial dataset in a DuckDB relational database for coverage analysis.

---

## Team Git Guidelines

To maintain code quality and collaboration, please follow this workflow for all contributions.

### ✋ Branch Policy

**Never push directly to `main`** — keep the main branch clean and working at all times.

Always work on feature branches for your assigned tasks:

```bash
git checkout -b feature/<role-or-task-name>
```

**Examples:**
- `feature/data-cleaning`
- `feature/api-augmentation`
- `feature/spatial-join`
- `feature/duckdb-schema`

### 🔄 Before Starting New Work

Sync your feature branch with the latest changes from main:

```bash
git checkout main
git pull origin main
git checkout feature/<your-branch>
git merge main
```

### 💬 Commit Guidelines

- **Commit frequently** with small, logical changes
- **Use descriptive messages** that clearly explain what changed
- **Example:** `git commit -m "Add coordinate matching logic for OCM API"`

### 🚫 Things to Avoid

- **Never force push** (`git push -f`) on shared branches
- **Never commit** CSV files, shapefiles, or `.duckdb` files (check `.gitignore`)

### ✅ Before Opening a Pull Request

1. Test your script locally to ensure it runs without breaking existing files
2. Verify `git status` shows no tracked data files
3. Only open a PR when your changes are ready for review

# charge-grid-nsw

A data engineering pipeline that integrates Transport for NSW EV charger data with ABS regional spatial boundaries. It augments DC fast chargers via external APIs and stores the final spatial dataset in a DuckDB relational database for coverage analysis.

## Git Workflow Guidelines

### Branch Policy

Never push directly to the `main` branch. The main branch must remain clean and functional at all times.

Create a feature branch for your assigned work before writing code:

```bash
git checkout -b feature/<role-or-task-name>
```

Common branch naming examples:

```
feature/data-cleaning
feature/api-augmentation
feature/spatial-join
feature/duckdb-schema
```

### Synchronizing Your Branch

Before starting new work, sync your branch with the latest changes from main:

```bash
git checkout main
git pull origin main
git checkout feature/<your-branch>
git merge main
```

### Commit Standards

- Commit frequently with small, logical changes
- Use clear, descriptive commit messages
- Example: `git commit -m "Add coordinate matching logic for OCM API"`

### Restrictions

Do not use force push on shared branches:

```bash
git push -f  # Do not use
```

Do not commit the following file types:

- CSV files
- Shapefiles
- DuckDB database files (`.duckdb`)

Verify these files are listed in `.gitignore` before committing.

### Pull Request Checklist

Before opening a pull request:

1. Test your code locally to confirm it runs without errors
2. Verify no data files are staged using `git status`
3. Ensure existing files and workflows are not broken by your changes
4. Submit the pull request when ready for review

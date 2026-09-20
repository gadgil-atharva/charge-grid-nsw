# charge-grid-nsw
A data engineering pipeline that integrates Transport for NSW EV charger data with ABS regional spatial boundaries. It augments DC fast chargers via external APIs and stores the final spatial dataset in a DuckDB relational database for coverage analysis.
Team Git Guidelines
Add this to your README.md or pin it in your group chat so everyone follows the same workflow:

Never push directly to main: Keep the main branch clean and working at all times.

Work on feature branches: Create a branch for your assigned role before writing code:

Bash
git checkout -b feature/<role-or-task-name>
# Examples: feature/data-cleaning, feature/api-augmentation, feature/spatial-join, feature/duckdb-schema
Sync before you start: Always pull the latest changes from main before starting new work:

Bash
git checkout main
git pull origin main
git checkout feature/<your-branch>
git merge main
Small, descriptive commits: Commit frequently with clear messages (e.g., git commit -m "Add coordinate matching logic for OCM API").

Never force push: Avoid git push -f on shared branches.

Test before opening a PR: Make sure your script runs locally without breaking existing files before opening a Pull Request into main.

Respect the .gitignore: Double-check git status before committing to ensure no .csv, shapefiles, or .duckdb files are staged.
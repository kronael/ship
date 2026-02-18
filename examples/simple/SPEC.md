# csv2json

## Goal

Python CLI tool that converts CSV files to JSON with
filtering and column selection.

## Deliverables

### 1. CLI entry point
- **Files**: main.py
- **Accept**: `python main.py data.csv` prints JSON to
  stdout, exits 0
- **Notes**: use click for argument parsing

### 2. Column selection
- **Files**: main.py
- **Accept**: `--columns name,age` outputs only those
  columns
- **Notes**: comma-separated column names

### 3. Row filtering
- **Files**: main.py
- **Accept**: `--where "age>30"` filters rows by
  numeric comparison
- **Notes**: support `>`, `<`, `=` operators. numeric
  comparisons only.

### 4. Output options
- **Files**: main.py
- **Accept**: `--output out.json` writes to file,
  `--pretty` indents output
- **Notes**: default output is stdout, compact JSON

### 5. Tests
- **Files**: test_main.py
- **Accept**: `pytest test_main.py` passes
- **Notes**: cover all flags, error cases (missing file,
  bad filter syntax, missing column)

## Constraints

- Python 3.12+, click for CLI, no other deps
- read CSV with stdlib csv module, not pandas
- exit 1 on invalid input with error message to stderr

## Verification

- [ ] `python main.py sample.csv` outputs valid JSON
- [ ] `python main.py sample.csv --columns name,age`
      selects only those columns
- [ ] `python main.py sample.csv --where "age>30"`
      filters correctly
- [ ] `python main.py missing.csv` exits 1
- [ ] `pytest test_main.py` passes

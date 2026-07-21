The file `calc.py` has a `format_price` function that formats an amount with a
currency symbol.

Add an optional `tax_rate` parameter to `format_price`:

- `tax_rate` is a float between 0 and 1 (e.g. 0.08 for 8%), default 0.
- When `tax_rate > 0`, the formatted amount includes tax: `amount * (1 + tax_rate)`.
- Update ALL callers of `format_price` to pass `tax_rate=0.0` explicitly (so the
  default behavior is unchanged but the call sites are explicit about tax).

Do NOT change anything else. Do NOT reformat the file. Do NOT add new features.

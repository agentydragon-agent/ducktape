## Source Code Inspection

`python3` is on your PATH with the full `props` library importable. Read any module:

```bash
python3 -c "import inspect, MODULE; print(inspect.getsource(MODULE))"
```

You can also write and run Python scripts with `exec`. Key modules:

% for mod, desc in modules:
- `${mod}` — ${desc}
% endfor

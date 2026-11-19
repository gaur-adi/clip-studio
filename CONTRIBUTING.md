# Contributing

Thanks for helping. Keep changes small and tested.

1. Fork and branch from `main`.
2. Set up: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
3. Run the tests before and after your change:
   ```bash
   cd tests && ../.venv/bin/python -m unittest discover -p "test_*.py"
   ```
4. Add tests for plan parsing, boundaries, metadata or anything else you touch. Use temp files; never write to `final/` or `data/` in tests.
5. Open a pull request describing what changed and how you checked it (a rendered clip is better evidence than a passing unit test).

Please do not commit secrets, streamer footage, music you do not have rights to, or model files. Report security issues privately through GitHub's security advisory feature.

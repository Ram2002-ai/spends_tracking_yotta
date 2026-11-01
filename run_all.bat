-@echo off
rem One-shot: docs + tests + starter + full dataset + reproducibility proof
python -m hfsynth docs || exit /b 1
python -m unittest discover -s tests || exit /b 1
python -m hfsynth generate --scale starter --out output_starter || exit /b 1
python -m hfsynth generate --scale full --out output || exit /b 1
python -m hfsynth repro --scale starter --out output_repro || exit /b 1
echo Done. See output\docs and output_repro\reproducibility_report.md

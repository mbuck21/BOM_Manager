PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PORT ?= 8501

.PHONY: setup run test

setup:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	streamlit run streamlit_app.py --server.port $(PORT) --server.address 0.0.0.0

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py"

# Read from the package so a release bump cannot leave this behind (it shipped 0.3.1
# images from 0.3.2 source).
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' mypeople/__init__.py)

.PHONY: wheel image verify clean

wheel:
	uv build --wheel --out-dir dist

image:
	docker build -t mypeople:$(VERSION) .

verify:
	mypeople verify

clean:
	rm -rf build .hatch dist/*.whl

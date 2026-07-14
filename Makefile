.PHONY: wheel image verify clean

wheel:
	uv build --wheel --out-dir dist

image:
	docker build -t mypeople:0.3.1 .

verify:
	mypeople verify

clean:
	rm -rf build .hatch dist/*.whl

.PHONY: clean upload test release

clean:
	find -name '*.pyc' -delete
	find -name '*.swp' -delete

upload:
	git push --tags; python setup.py clean sdist upload

test:
	./test.py

release:
	git push; git push --tags; python setup.py clean sdist upload

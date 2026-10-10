# DevOS Master Makefile
.PHONY: help setup iso iso-docker test-qemu-bios test-qemu-uefi clean lint check-size

SHELL := /bin/bash
IMAGE_NAME := devos-builder
ISO_OUTPUT := out/devos-24.04-amd64.iso

help:
	@echo "DevOS Build System"
	@echo "=================="
	@echo "  make setup            - Install host build tools (Ubuntu 24.04 required)"
	@echo "  make iso              - Build DevOS live hybrid ISO natively (requires root)"
	@echo "  make iso-docker       - Build DevOS live ISO inside containerized environment"
	@echo "  make test-qemu-bios   - Test generated ISO in QEMU (Legacy BIOS mode)"
	@echo "  make test-qemu-uefi   - Test generated ISO in QEMU (UEFI / OVMF mode)"
	@echo "  make check-size       - Audit package and ISO size breakdown"
	@echo "  make lint             - Run shell script and config linters"
	@echo "  make clean            - Remove build workdir and outputs"

setup:
	@echo "==> Running host environment setup..."
	sudo ./build/setup-build-env.sh

iso:
	@echo "==> Building DevOS ISO natively..."
	sudo ./build/build-iso.sh

iso-docker:
	@echo "==> Building containerized build environment..."
	docker build -t $(IMAGE_NAME) -f build/docker/Dockerfile.build .
	@echo "==> Building DevOS ISO inside container..."
	docker run --rm --privileged \
		-v "$(CURDIR):/workspace" \
		$(IMAGE_NAME) make iso

test-qemu-bios:
	@echo "==> Launching DevOS in QEMU (BIOS mode)..."
	./tests/qemu/run-qemu-test.sh bios

test-qemu-uefi:
	@echo "==> Launching DevOS in QEMU (UEFI mode)..."
	./tests/qemu/run-qemu-test.sh uefi

check-size:
	@echo "==> Checking size metrics..."
	@if [ -f "$(ISO_OUTPUT)" ]; then \
		ls -lh "$(ISO_OUTPUT)"; \
		du -h "$(ISO_OUTPUT)"; \
	else \
		echo "ISO not yet generated. Run 'make iso' first."; \
	fi

lint:
	@echo "==> Running script validation..."
	@which shellcheck >/dev/null 2>&1 && shellcheck build/*.sh build/hooks/*.hook.chroot tests/qemu/*.sh || echo "shellcheck not installed, skipping."

clean:
	@echo "==> Cleaning work directory..."
	sudo rm -rf build_work out

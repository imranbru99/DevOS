# DevOS Master Makefile
.PHONY: help setup iso iso-docker test-qemu-bios test-qemu-uefi test-usb-bios test-usb-uefi verify-iso clean lint check-size

SHELL := /bin/bash
IMAGE_NAME := devos-builder:26.04
ISO_OUTPUT := out/devos-26.04-amd64.iso

help:
	@echo "DevOS Build System"
	@echo "=================="
	@echo "  make setup            - Install host build tools (Ubuntu 26.04 required)"
	@echo "  make iso              - Build DevOS live hybrid ISO natively (requires root)"
	@echo "  make iso-docker       - Build DevOS live ISO inside containerized environment"
	@echo "  make verify-iso       - Verify an existing ISO boots on real hardware"
	@echo "  make test-qemu-bios   - Test generated ISO in QEMU (Legacy BIOS mode, CD)"
	@echo "  make test-qemu-uefi   - Test generated ISO in QEMU (UEFI / OVMF mode, CD)"
	@echo "  make test-usb-bios    - Test dd-written ISO as a USB disk under QEMU SeaBIOS"
	@echo "  make test-usb-uefi    - Test dd-written ISO as a USB disk under QEMU OVMF"
	@echo "  make check-size       - Audit package and ISO size breakdown"
	@echo "  make lint             - Run shell script and config linters"
	@echo "  make clean            - Remove build workdir and outputs"

setup:
	@echo "==> Running host environment setup..."
	sudo bash ./build/setup-build-env.sh

iso:
	@echo "==> Building DevOS ISO natively..."
	sudo bash ./build/build-iso.sh
	@echo "==> Verifying ISO real-hardware boot layout..."
	bash ./tests/boot/verify-iso-bootability.sh "$(ISO_OUTPUT)"

iso-docker:
	@echo "==> Building containerized build environment..."
	docker build -t $(IMAGE_NAME) -f build/docker/Dockerfile.build .
	@echo "==> Building DevOS ISO inside container..."
	docker run --rm --privileged \
		-e DEVOS_WORK_DIR="/workspace/build_work/resolute" \
		-e DEVOS_ZSTD_LEVEL="15" \
		-v "$(CURDIR):/workspace" \
		$(IMAGE_NAME) bash -c 'bash ./build/build-iso.sh && bash ./tests/boot/verify-iso-bootability.sh out/devos-26.04-amd64.iso'

verify-iso:
	@echo "==> Verifying ISO real-hardware boot layout..."
	@./tests/boot/verify-iso-bootability.sh "$(ISO_OUTPUT)"

test-qemu-bios:
	@echo "==> Launching DevOS in QEMU (BIOS mode)..."
	./tests/qemu/run-qemu-test.sh bios

test-qemu-uefi:
	@echo "==> Launching DevOS in QEMU (UEFI mode)..."
	./tests/qemu/run-qemu-test.sh uefi

test-usb-bios:
	@echo "==> Launching DevOS USB-stick image in QEMU (BIOS mode)..."
	./tests/qemu/run-usb-boot-test.sh bios

test-usb-uefi:
	@echo "==> Launching DevOS USB-stick image in QEMU (UEFI mode)..."
	./tests/qemu/run-usb-boot-test.sh uefi

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
	@which shellcheck >/dev/null 2>&1 && shellcheck build/*.sh build/hooks/*.hook.chroot tests/qemu/*.sh tests/boot/*.sh || echo "shellcheck not installed, skipping."

clean:
	@echo "==> Cleaning work directory..."
	sudo rm -rf build_work out

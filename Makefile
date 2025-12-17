embed:
	python3 scripts/embed_images_in_html.py --src pages --out embedded_pages

build-images: embed
	python3 scripts/html_to_images.py --src embedded_pages --out output_images
	python3 scripts/create_build.py --pages embedded_pages --images output_images --videos output_videos --build build

#videos:
videos:
	@echo 'Generating 5s videos from output_images/ into output_videos/5s using ffmpeg'
	python3 scripts/images_to_videos.py --src output_images --out output_videos/5s --duration 5 --width 1920 --height 1080

build-videos: build-images videos
	@echo 'Build and video creation done.'

## removed old record-playwright/records targets (duplicate)

record-playwright:
	python3 scripts/pages_record_playwright.py --src embedded_pages --out output_videos --durations 5 --width 1920 --height 1080

record-playwright-long:
	python3 scripts/pages_record_playwright.py --src embedded_pages --out output_videos --durations 10 60 --width 1920 --height 1080

build-record-playwright: build-images record-playwright
	python3 scripts/create_build.py --pages embedded_pages --images output_images --videos output_videos --build build
	@echo 'Build, playright record, and create build done.'

build-record-playwright-long: build-images record-playwright-long
	python3 scripts/create_build.py --pages embedded_pages --images output_images --videos output_videos --build build
	@echo 'Build, playright record (long), and create build done.'

build-images-direct:
	python3 scripts/html_to_images.py --src pages --out output_images
	python3 scripts/create_build.py --pages pages --images output_images --videos output_videos --build build

build-videos-direct: build-images-direct videos
	@echo 'Build (direct) and video creation done.'

upload:
	@# Upload videos to SharePoint using rclone. Provide RCLONE_REMOTE env var or pass as param
	@if [ -z "${RCLONE_REMOTE}" ]; then echo "Please set RCLONE_REMOTE=remote:path"; exit 1; fi
	./scripts/upload_to_sharepoint.sh "${RCLONE_REMOTE}"

serve:
	@echo "Serving build/ on http://localhost:${PORT:=8000} (Ctrl-C to stop)"
	python3 -m http.server ${PORT:=8000} --directory build

serve-bg:
	@mkdir -p build
	@PORT=${PORT:=8000}; PORT=$$PORT nohup python3 -m http.server $$PORT --directory build > build/serve.log 2>&1 & echo $$! > build/serve.pid; echo "Server started on http://localhost:$$PORT (pid $$(cat build/serve.pid))"

serve-stop:
	@if [ -f build/serve.pid ]; then kill $$(cat build/serve.pid) 2>/dev/null || true; rm -f build/serve.pid; echo "Stopped serve-bg"; else echo "No serve PID file found"; fi

serve-logs:
	@tail -n +1 -f build/serve.log || true

watch:
	python3 scripts/watch_and_build.py --pages pages --embedded embedded_pages --out output_images

install-cron:
	bash scripts/install_cron.sh


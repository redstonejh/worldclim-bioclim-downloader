# WorldClim/BioClim GSP Archive Downloader

This project downloads and organizes WorldClim/BioClim climate rasters for a GSP archive. It was built to make the archive reproducible, resumable, and safer to run with very large climate datasets.

The project includes:

- `download_worldclim.py`: command-line downloader
- `worldclim_gui.py`: simple desktop GUI for running the downloader
- `requirements.txt`: Python package dependencies
- `example_manifest.csv`: example of the manifest format produced by the script

## What It Downloads

By default, the full archive command downloads:

- All current WorldClim v2.1 raster ZIPs from the official WorldClim base directory
- All current BioClim rasters at all available resolutions
- One representative future CMIP6 climate dataset:
  - Resolution: `2.5m`
  - Model: `MIROC6`
  - Scenario: `ssp245`
  - Periods: all available future periods listed by WorldClim
  - Variables: minimum temperature, maximum temperature, precipitation, and bioclimatic variables when available

The script intentionally does not download every future model and scenario combination, because the full CMIP6 future archive would be extremely large.

## Data Sources

The downloader reads file listings from official WorldClim pages:

- Current WorldClim v2.1 data: https://geodata.ucdavis.edu/climate/worldclim/2_1/base/
- Current WorldClim documentation: https://www.worldclim.org/data/worldclim21.html
- CMIP6 future documentation: https://www.worldclim.org/data/cmip6/cmip6climate.html
- Future 2.5 minute data page: https://www.worldclim.org/data/cmip6/cmip6_clim2.5m.html

## Features

- Resumable downloads using HTTP range requests when supported by the server
- Skips files that already exist and match the expected remote size
- Retries failed downloads with exponential backoff
- Progress bars for command-line downloads
- GUI option for users who prefer not to run commands manually
- Dry-run mode to preview what will be downloaded before downloading data
- Timestamped log files
- Timestamped CSV manifests recording URL, local path, file size, dataset type, model, scenario, period, and status
- Organized output folder structure suitable for an archive

## Storage Warning

WorldClim data can be very large. The current 30 second rasters include multi-GB ZIP files, and a full current archive can require tens of GB before any files are extracted.

This script downloads the ZIP and TIF files only. It does not unzip or process raster contents.

Before running the full download, use dry-run mode and make sure the destination drive has enough free space.

## Requirements

- Python 3.10 or newer recommended
- Internet connection
- Enough disk space for large raster downloads

Python packages are listed in `requirements.txt`:

- `requests`
- `beautifulsoup4`
- `tqdm`

Tkinter is used for the GUI and is included with most standard Python installations on Windows and macOS.

## Setup

Clone or download this repository, then open a terminal in the project folder.

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

Activate it on macOS or Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Recommended First Step: Dry Run

Run a dry run before downloading. This checks the WorldClim pages, lists the planned files, and writes a manifest without downloading raster data.

```bash
python download_worldclim.py --all --output worldclim_archive --dry-run
```

A successful dry run should report the planned files and exit with code `0`.

## Full Command-Line Download

To download the full planned archive:

```bash
python download_worldclim.py --all --output worldclim_archive
```

This creates the archive folder and organizes data like this:

```text
worldclim_archive/
  current/
    base/
    bioclim/
  future/
    cmip6/
      2.5m/
        MIROC6/
          ssp245/
  logs/
  manifests/
```

If the download is interrupted, run the same command again. Complete files are skipped and partial files are resumed when possible.

## GUI Usage

Launch the graphical interface:

```bash
python worldclim_gui.py
```

The GUI lets you choose:

- Output folder
- Current base rasters
- Current BioClim rasters
- Future CMIP6 rasters
- Resolution
- Future model
- Future scenario
- Retry count
- Timeout

Use **Dry Run** first to preview the planned files. Use **Download** when ready to begin downloading. The log panel shows the command output from the downloader.

## Common Examples

Download everything requested for the GSP archive:

```bash
python download_worldclim.py --all --output worldclim_archive
```

Preview everything without downloading:

```bash
python download_worldclim.py --all --output worldclim_archive --dry-run
```

Download only current non-BioClim WorldClim rasters:

```bash
python download_worldclim.py --current --output worldclim_archive
```

Download only current BioClim rasters:

```bash
python download_worldclim.py --bioclim --output worldclim_archive
```

Download only the representative future CMIP6 dataset:

```bash
python download_worldclim.py --future --output worldclim_archive
```

Download only 10 minute current rasters:

```bash
python download_worldclim.py --current --bioclim --resolution 10m --output worldclim_archive
```

Change the future model, scenario, or resolution:

```bash
python download_worldclim.py --future --resolution 5m --model ACCESS-CM2 --scenario ssp585 --output worldclim_archive
```

For future downloads, `--resolution all` uses the representative default resolution, `2.5m`. To select a different CMIP6 future page, use `30s`, `2.5m`, `5m`, or `10m`.

## Command-Line Options

```text
--all              Download current base, current BioClim, and future CMIP6 data
--current          Download current non-BioClim WorldClim rasters
--bioclim          Download current BioClim rasters
--future           Download one representative future CMIP6 dataset
--output           Output archive directory
--resolution       all, 10m, 5m, 2.5m, or 30s
--model            Future CMIP6 GCM model, default MIROC6
--scenario         Future CMIP6 scenario, default ssp245
--dry-run          Print planned downloads and write a manifest without downloading
--retries          Retry attempts per file, default 4
--timeout          HTTP timeout in seconds, default 60
--chunk-size       Download chunk size in bytes
--no-progress      Disable terminal progress bars
```

## Manifest

Every run writes a timestamped CSV manifest under:

```text
worldclim_archive/manifests/
```

The manifest includes:

- `url`
- `local_path`
- `file_size`
- `dataset_type`
- `model`
- `scenario`
- `period`
- `download_status`

This makes it easier to review what was planned, downloaded, skipped, resumed, or failed.

## Logs

Every run writes a timestamped log under:

```text
worldclim_archive/logs/
```

Logs are useful for troubleshooting failed downloads or documenting archive creation.

## GitHub Notes

The repository is intended to store the downloader code and documentation, not the downloaded raster data.

The `.gitignore` file excludes:

- `worldclim_archive/`
- Python cache files
- local virtual environments
- editor and operating system files

Do not commit downloaded WorldClim rasters to GitHub. They are too large and should be regenerated with the script or stored in the intended archive location.

## Citation And Credit

Please credit WorldClim when using these data. WorldClim lists the citation:

Fick, S.E. and R.J. Hijmans, 2017. WorldClim 2: new 1km spatial resolution climate surfaces for global land areas. International Journal of Climatology 37 (12): 4302-4315.

Also review WorldClim and CMIP6 terms and citation guidance:

- https://www.worldclim.org/data/worldclim21.html
- https://www.worldclim.org/data/cmip6/cmip6climate.html

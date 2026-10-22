# Gallery storage on a dedicated drive, and importing a large library

This is the runbook for moving the ES Photos gallery onto its own drive and bringing
in a large photo library (tens of thousands of files), replacing a Piwigo server.

It is written for the Enterprise Systems setup:

| | |
|---|---|
| Proxmox host | `192.168.0.3` (node `enterprisesystems`) |
| ERP server | VM **101** `ES-HP-ERPv15-v1` — `192.168.0.77`, bench at `/home/enterprise/frappe-bench`, runs as user `enterprise` |
| Piwigo server | VM **102** `ES-HP-Piwigo` — `192.168.0.131` (photos.tarrant-trading.com) |
| Photo drive | WD Elements SE 4 TB USB — `/dev/disk/by-id/usb-WD_Elements_SE_2623_57583732443233394A464C58-0:0` |
| Site | `erp.enterprisesystems.com.au` → gallery at `/social/gallery` |

Run the commands **one line at a time**, and replace nothing in `<angle brackets>` without
reading the note next to it.

---

## How it fits together

```
/mnt/photos                      ← the 4 TB drive (ext4)
└── es_photos/                   ← bind-mounted onto sites/<site>/public/files/es_photos
    ├── <photo>-th.jpg …          resized copies made by ES Photos
    ├── originals/                photos uploaded in the gallery or copied in from Piwigo
    └── library/                  YOUR folders of photos → albums (Import folder job)
        ├── Walpole WA 2026/
        │   ├── Coalmine Beach/   → album "Coalmine Beach" inside "Walpole WA 2026"
        │   └── IMG_0001.JPG
        └── …
```

* Everything under `es_photos/` is served by nginx at `/files/es_photos/…` and is
  **left out of the Google Drive backup** (ES Photos Settings → Backups).
* Files in `library/` are used where they are; ES Photos only adds small resized copies.
  Anything placed in `library/` can be fetched by URL even before it is imported or if its
  album is private — keep private material out of it.

---

## Step 0 — before anything is erased

The drive is currently formatted **APFS** (Mac) and attached to the Piwigo VM.
Formatting it in step 3 **erases everything on it**. Copy off anything you need first.

Check where Piwigo keeps its photos (inside VM 102):

```bash
df -h /var/www/html/piwigo/galleries
```

If it shows the VM's own disk (`/dev/sda…` or `/dev/mapper/…`), Piwigo keeps working after
the drive is detached — continue below. If it shows the USB drive, stop and ask: the
copy-in (step 5) needs Piwigo running.

## Step 1 — install ES Photos 0.6.0

> If Frappe itself was updated as well (e.g. by `bench update`), install its new Python
> requirements **before** migrating — recent Frappe v15 releases need `duckdb` and `pyarrow`:
> `bench setup requirements --python`. Otherwise migrate stops with
> `No module named 'pyarrow'`.

```bash
cd ~/frappe-bench
git -C apps/es_photos pull                   # updates ES Photos only — not Frappe or other apps
bench --site erp.enterprisesystems.com.au migrate
bench build --app es_photos
sudo supervisorctl restart all
```

More background workers make the import faster (each processes one photo at a time; the VM
has the RAM for 3):

```bash
bench set-config -g background_workers 3
bench setup supervisor --yes
sudo supervisorctl reread && sudo supervisorctl update
sudo supervisorctl status | grep long-worker     # should list 3 long workers
```

## Step 2 — move the drive from the Piwigo VM to the ERP VM (Proxmox host)

On the Proxmox host (web UI → node → Shell):

```bash
qm config 102 | grep -i -E "WD_Elements|usb"
```

Note the key at the start of that line (e.g. `scsi1` or `usb0`). If the drive is mounted inside
VM 102, unmount it there first (`sudo umount <mount point>`), then:

```bash
qm set 102 --delete scsi1          # use the key you noted
qm set 101 -scsi1 /dev/disk/by-id/usb-WD_Elements_SE_2623_57583732443233394A464C58-0:0
```

## Step 3 — format and mount the drive (ERP VM 101)

```bash
lsblk -o NAME,SIZE,MODEL,FSTYPE
```

The drive is the ~3.6T disk, normally `sdb`. **Check the name — the next three commands
erase it.**

```bash
sudo wipefs -a /dev/sdb
sudo parted -s /dev/sdb mklabel gpt mkpart photos ext4 0% 100%
sudo mkfs.ext4 -L photos -m 1 /dev/sdb1
```

Mount it at boot by its label (`nofail` keeps the VM booting if the drive is unplugged):

```bash
sudo mkdir -p /mnt/photos
echo 'LABEL=photos  /mnt/photos  ext4  defaults,noatime,nofail,x-systemd.device-timeout=10  0  2' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount /mnt/photos
df -h /mnt/photos                   # should show ~3.6T
```

## Step 4 — move the gallery's storage onto the drive

```bash
SITE=/home/enterprise/frappe-bench/sites/erp.enterprisesystems.com.au
sudo mkdir -p /mnt/photos/es_photos/library
sudo chown -R enterprise:enterprise /mnt/photos/es_photos
rsync -a $SITE/public/files/es_photos/ /mnt/photos/es_photos/
mv $SITE/public/files/es_photos $SITE/public/files/es_photos.old
mkdir $SITE/public/files/es_photos
echo "/mnt/photos/es_photos  $SITE/public/files/es_photos  none  bind,nofail,x-systemd.requires-mounts-for=/mnt/photos  0  0" | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount $SITE/public/files/es_photos
ls $SITE/public/files/es_photos | head      # the same files as before, now on the drive
```

Open `/social/gallery` and check uploaded photos still show. When happy:
`rm -rf $SITE/public/files/es_photos.old`.

## Step 5 — copy the photos still shown from Piwigo into the ERP server

About 7,400 gallery photos are still loaded from photos.tarrant-trading.com. While Piwigo is
running:

*Optional, much faster:* make the ERP VM fetch from Piwigo over the LAN instead of via the
internet — add a hosts entry, check it, and remove it again after step 5:

```bash
echo '192.168.0.131  photos.tarrant-trading.com' | sudo tee -a /etc/hosts
curl -sI https://photos.tarrant-trading.com/ | head -1      # must say HTTP/… 200 or 30x
```

(If that curl fails — e.g. certificate errors because Piwigo's HTTPS is terminated elsewhere —
remove the line again: `sudo sed -i '/photos.tarrant-trading.com/d' /etc/hosts`.)

Then in the desk: **ES Photos → Library jobs → + Add**
* Job: **Copy linked photos in**
* What to copy: **Original (full size)** (~114 GB) or **Large copy only** (~3 GB)
* Save → **Start**

Progress shows on the job (it refreshes itself). Albums, comments and reactions stay.
When it finishes, run it once more — it should report *0 photos are still shown from another
website*. Remove the hosts line if you added it.

## Step 6 — import your photo library

Copy folders of photos into `/mnt/photos/es_photos/library/`. Each folder becomes an album,
sub-folders become sub-albums. From a Mac or another Linux machine on the network:

```bash
rsync -av --progress "/Volumes/MyPhotos/Exports/" enterprise@192.168.0.77:/mnt/photos/es_photos/library/
```

(Windows: WinSCP to the same folder.) Then **ES Photos → Library jobs → + Add**:
* Job: **Import folder**
* Sub-folder: blank for everything, or e.g. `Walpole WA 2026`
* Put albums inside / Album owner / Privacy: as you like
* Tick **Dry run** the first time → **Start** → read the log (it lists what it would add).
* Untick Dry run → **Run again**.

Photos appear in the gallery as their resized copies are made. Expect roughly
1–2 photos per second per worker for full-size camera files — with 3 workers, 100,000 photos
takes roughly half a day to a day. You can keep using the site meanwhile; **Cancel** stops after the current
photo and **Run again** carries on where it stopped.

Re-run the job whenever you add more folders: only new or changed files are processed, and
(if ticked) photos whose files were removed are hidden.

Supported: JPEG, PNG, WebP, GIF, TIFF, BMP. iPhone HEIC/HEIF files need one extra package:

```bash
cd ~/frappe-bench && ./env/bin/pip install pillow-heif && sudo supervisorctl restart all
```

Video files are skipped (add videos to the gallery as YouTube/Vimeo links).

## Step 7 — retire Piwigo

When step 5 reports 0 remaining photos and the gallery looks right, shut down VM 102.

## Backups

The gallery folder is not in the Google Drive backup. Keep a second copy of
`/mnt/photos/es_photos` — for example a nightly rsync to another disk or NAS:

```bash
rsync -a --delete /mnt/photos/es_photos/ /path/to/second/disk/es_photos/
```

A single USB drive is a single point of failure.

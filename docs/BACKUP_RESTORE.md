# Backup and restore (for the shop owner)

## What is backed up
Everything: bills, payments, customers and udhar, stock, expenses, jobs, applications, settings and rates.
A backup is **one file**, e.g. `xeroxpro-20261106-183000-auto.db`. The date and time are in the name.

## Automatic backups
- A backup is made **automatically once a day** when the program starts, and again when you close it (unless one
  was made in the last 4 hours). The last 60 automatic backups are kept; older ones are removed.
- Backups you make yourself ("Back up now"), copies to USB, and safety copies made before a restore are **never removed**.
- If there has been no backup for 2 days, a red reminder appears on the Dashboard.

## Where the backups go
Default: `Documents\XeroxPro Backups` (not the folder where the data lives). Change it under *Backup & Restore ->
Change folder*. The program warns if you pick a folder next to the data itself. Best practice: also keep a copy on a
USB stick or another drive.

## Make a backup now
*Backup & Restore -> Back up now.* The new file appears in the list.

## Copy to a USB stick
Plug in the USB stick, press *Copy to USB / another folder*, choose the stick. The copy is checked before it is saved.

## Restore (go back to an earlier state)
1. *Backup & Restore*, click the backup in the list (or press *Restore from a file...* for a file from a USB stick).
2. Press *Restore selected backup*. The program first checks the file. A damaged or foreign file is refused and
   **nothing changes**.
3. Read the warning: everything entered after the backup's time will be replaced.
4. If an owner PIN is set, enter it.
5. A **safety copy of your current data is saved first** (type "Safety copy before restore"). If you restored the wrong
   file, restore that safety copy to get everything back.

## Moving to a new computer
Install the program, copy a backup file to the new computer, then *Restore from a file...*.

## If something goes wrong
- "Cannot write to that folder": the folder or USB stick is not available or full. Choose another.
- "Not a valid backup": the file is damaged or is not a XeroxPro backup. Try an older backup from the list.
- "Made by a newer version": install the latest version of the program first.
- Backups are never overwritten. A backup interrupted by a power cut leaves no half-written file.

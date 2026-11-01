# Target records by JetPack release

Last updated: 2026-10-31

Declared target records for recent JetPack releases, to pass to `--target`. Each states the Jetson Linux (L4T), CUDA
and TensorRT versions NVIDIA publishes for that release, the page they were read from and the date it was read. They
are declarations: the tool compares an image with them, and nothing here was read from a device. They are examples to
check against your own device, not a compatibility table the tool consults.

| Record | JetPack | Jetson Linux | CUDA | TensorRT | Source, retrieved |
|---|---|---|---|---|---|
| [jetpack-6.2.3.json](jetpack-6.2.3.json) | 6.2.3 | 36.5.2 | 12.6.10 | 10.3.0 | [jetpack-sdk-623](https://developer.nvidia.com/embedded/jetpack-sdk-623) and [jetson-linux-r3652](https://developer.nvidia.com/embedded/jetson-linux-r3652), 2026-10-29 |
| [jetpack-6.2.1.json](jetpack-6.2.1.json) | 6.2.1 | 36.4.4 | 12.6.10 | 10.3.0 | [jetpack-sdk-621](https://developer.nvidia.com/embedded/jetpack-sdk-621), 2026-10-30 |
| [jetpack-6.2.json](jetpack-6.2.json) | 6.2 | 36.4.3 | 12.6.10 | 10.3.0 | [jetpack-sdk-62](https://developer.nvidia.com/embedded/jetpack-sdk-62), 2026-10-30 |
| [jetpack-6.1.json](jetpack-6.1.json) | 6.1 | 36.4 | 12.6.10 | 10.3.0 | [jetpack-sdk-61](https://developer.nvidia.com/embedded/jetpack-sdk-61), 2026-10-30 |
| [jetpack-5.1.8.json](jetpack-5.1.8.json) | 5.1.8 | 35.7.0 | 11.4.19 | 8.5.2 | [jetpack-sdk-518](https://developer.nvidia.com/embedded/jetpack-sdk-518), 2026-10-30 |

JetPack 6.2.3: these values were relayed from a reading of the two pages on 2026-10-29 and have not been re-read by the
maintainer; re-read both pages before relying on the record, and update the retrieval date when you do. The 6.2.3 SDK
page's introduction still names JetPack 6.2.2 and 6.2.1, so the record uses the page's explicit, component-specific
6.2.3 statements. NVIDIA's apt package index for the r36.5 suite
(`https://repo.download.nvidia.com/jetson/common/dists/r36.5/main/binary-arm64/Packages.gz`, read 2026-10-29) lists
`cuda-toolkit-12-6` 12.6.11-1 where the SDK page says CUDA 12.6.10; the reason is not established, so a device whose
installed CUDA is 12.6.11 will not match this record, which is the correct reading of a mismatch.

JetPack 5.1.8 is the newest 5.1.x release NVIDIA's [JetPack archive](https://developer.nvidia.com/embedded/jetpack-archive)
listed on 2026-10-30. The JetPack 6.1 page states Jetson Linux as 36.4, without a patch number, so the record does too.

## Use

```sh
egrit-preflight image --image IMAGE_REF --target examples/targets/jetpack-6.2.json
```

Pick the release your device runs (`cat /etc/nv_tegra_release` on the device names its Jetson Linux release). Once you
have read the versions from the device itself, copy the record, set them, and keep `status` as `declared` until an
observed procedure exists.

These files are the source. An optional helper, such as Egrit's client (not publicly released yet) described in
[where it fits](../../docs/where-it-fits.md#optional-egrit-alongside-preflight), returns them unchanged; it adds no
release this table does not have.

## Adding a release

1. Open the release's page from NVIDIA's [JetPack archive](https://developer.nvidia.com/embedded/jetpack-archive) on the
   day you write the record. Use NVIDIA's own pages only, never a forum reply or another project's table.
2. Copy the JetPack, Jetson Linux, CUDA and TensorRT versions exactly as the page writes them. Where the page does not
   state a value, write `"not established"`, which the tool reports as UNKNOWN; never fill it from memory.
3. Name the file `jetpack-<version>.json`, with `architecture: aarch64`, `status: declared`, and one `sources` entry
   holding the page URL and `retrieved` as `YYYY-MM-DD`.
4. Add a row to the table above in the same commit. `tests/test_examples.py` fails if a record is missing from it, if a
   source is not an NVIDIA page or has no date, or if a record does not load.

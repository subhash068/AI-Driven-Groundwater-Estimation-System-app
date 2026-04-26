# Fix RuntimeWarning: Mean of empty slice

## Steps
1. [x] Read and understand `scripts/build_authoritative_krishna_data.py`
2. [x] Refactor lines 449–450 (`obs_elevation_msl_mean`, `obs_total_depth_m`) to avoid duplicate `np.nanmean` on empty slices
3. [x] Refactor line 460 (`depth_dm`) with the same safe-mean pattern
4. [x] Verify the script runs without warnings



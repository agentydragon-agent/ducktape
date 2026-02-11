# Prevent pytest from collecting test files inside snapshot code/ directories.
# Specimen code is frozen third-party data, not our test suite.
collect_ignore_glob = ["*"]

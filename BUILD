load("@rules_python//python/pip_install:requirements.bzl", "compile_pip_requirements")

# Convenient way to update.
compile_pip_requirements(
    name = "requirements",
    extra_args = ["--allow-unsafe"],
    requirements_in = "requirements.in",
    requirements_txt = "requirements_lock.txt",
)

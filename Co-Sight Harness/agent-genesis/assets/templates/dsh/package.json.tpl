{
  "name": "{{package_name}}",
  "version": "{{version}}",
  "description": "{{description}}",
  "type": "module",
  "files": [
    "cordis.patch.yml",
    "README.md",
    "install.sh",
    "skills",
    "rules"
  ],
  "dsh": {
    "bundle": {
      "patch": "./cordis.patch.yml"
    }
  }
}

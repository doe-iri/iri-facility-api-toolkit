#!/usr/bin/env python3
"""
Generate Python client from ESnet IRI OpenAPI specification.

This script can be used standalone or imported into CI/CD pipelines.

Credit: https://gitlab.com/amsc2/infrastructure-and-services/amsc-interfaces/amsc-api-python
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError


DEFAULT_API_URL = "https://iri-dev.ppg.es.net/openapi.json"
CONFIG_FILE = "config.yaml"
OUTPUT_DIR = "generated"


def check_api_accessibility(api_url: str) -> bool:
    """Check if the API is accessible."""
    try:
        with urlopen(api_url, timeout=5) as response:
            return response.status == 200
    except (URLError, Exception):
        return False


def check_tool_installed() -> bool:
    """Check if openapi-python-client is installed."""
    return shutil.which("openapi-python-client") is not None


def generate_client(api_url: str, config_file: str, output_dir: str, package_name: str) -> bool:
    """
    Generate the Python client.
    
    Returns:
        True if generation was successful, False otherwise.
    """
    script_dir = Path(__file__).parent
    config_path = script_dir / config_file
    output_path = script_dir / output_dir
    
    # Remove existing generated client
    if output_path.exists():
        print(f"🗑️  Removing existing generated client at {output_path}")
        shutil.rmtree(output_path)
    
    # Build command
    #cmd = [
    #    "openapi-python-client",
    #    "generate",
    #    "--url", api_url,
    #    "--config", str(config_path),
    #    "--output-path", str(output_path),
    #]
    
    cmd = [
        "openapi-generator",
        "generate",
        "-i", api_url,
        "-g", "python",
        "-o", str(output_path),
        "--package-name", str(package_name)
    ]
    
    print(f"⚙️  Generating Python client...")
    print(f"   Command: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(
            cmd,
            cwd=script_dir,
            check=True,
            capture_output=False,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"❌ Generation failed with exit code {e.returncode}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate Python client from ESnet IRI OpenAPI specification"
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"OpenAPI JSON URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--config",
        default=CONFIG_FILE,
        help=f"Config file path (default: {CONFIG_FILE})",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Skip API accessibility check",
    )
    parser.add_argument(
        "--package-name",
        default="esnet_iri",
        help="Package name (default: esnet_iri)",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  ESnet IRI Python Client Generator")
    print("=" * 60)
    print()
    print(f"API URL: {args.api_url}")
    print(f"Config:  {args.config}")
    print(f"Output:  {args.output}")
    print(f"Package name:  {args.package_name}")
    print()
    
    # Check if tool is installed
    if not check_tool_installed():
        print("❌ openapi-generator is not installed")
        print()
        print("To install (macOS), run:")
        print("  brew install openapi-generator")
        print()
        sys.exit(1)
    
    # Check API accessibility
    if not args.skip_check:
        print("🔍 Checking API accessibility...")
        if check_api_accessibility(args.api_url):
            print("✓ API is accessible")
            print()
        else:
            print(f"❌ Cannot access API at {args.api_url}")
            print()
            print("Make sure the API server is running:")
            print("  make")
            print()
            print("Or use --skip-check to bypass this check")
            print()
            sys.exit(1)
    
    # Generate client
    if generate_client(args.api_url, args.config, args.output, args.package_name):
        print()
        print("=" * 60)
        print("  ✅ Client generated successfully!")
        print("=" * 60)
        print()
        print(f"Location: {args.output}")
        print()
        print("To install the client:")
        print(f"  cd {args.output}")
        print("  pip install -e .")
        print()
        print("To run tests:")
        print("  python tests/test_workflow_simple.py")
        print()
        sys.exit(0)
    else:
        print()
        print("❌ Client generation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()


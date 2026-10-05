# Security Policy

ECCO-Pro can interact with energy-control equipment, so security reports are taken seriously.

## Reporting a vulnerability

Please do not publish credentials, private household data, or a working exploit in a public issue.

For security-sensitive reports, use GitHub's private vulnerability reporting feature when it is enabled for this repository. If private reporting is unavailable, contact the maintainer through the GitHub account associated with this repository and avoid including secrets until a private channel has been established.

## Scope

Security-sensitive areas include:

- inverter write paths and transaction handling
- authentication, secrets, and local configuration
- GitHub Actions and supply-chain behaviour
- Home Assistant service exposure
- update and deployment mechanisms
- data handling that could expose household or account information

## Supported versions

A supported-version policy will be added before the first public release.

## Safety

A security issue that could cause unintended inverter writes or unsafe control behaviour should be treated as both a security and safety issue.

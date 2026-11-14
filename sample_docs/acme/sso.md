# Single Sign-On (SSO)

SSO is available on the Enterprise plan. Acme Cloud supports SAML 2.0 and OpenID Connect.
Supported identity providers include Okta, Microsoft Entra ID, Google Workspace and any standards-compliant SAML provider.

## Setting up SAML

1. In Acme Cloud, open Settings > Security > Single Sign-On and choose SAML.
2. Copy the Assertion Consumer Service (ACS) URL and the Entity ID into your identity provider.
3. Upload the identity provider metadata XML back into Acme Cloud.
4. Test the connection with a non-admin account before enforcing SSO.

## Enforcing SSO

Once SSO is enforced, password login is disabled for everyone except the break-glass owner account.
SCIM provisioning automatically creates and deactivates users when they are assigned or removed in the identity provider.

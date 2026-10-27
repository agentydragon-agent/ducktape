package main

import (
	"fmt"
	"net/url"
)

// FrontendConfig is the browser-safe subset of deployment settings.
type FrontendConfig struct {
	TraceSearch    *TraceSearchSettings    `mapstructure:"trace_search" json:"trace_search" nullable:"true"`
	LangfuseSearch *LangfuseSearchSettings `mapstructure:"langfuse_search" json:"langfuse_search" nullable:"true"`
}

type TraceSearchSettings struct {
	GrafanaBaseURL        string `mapstructure:"grafana_base_url" json:"grafana_base_url" format:"uri"`
	TempoDatasourceUID    string `mapstructure:"tempo_datasource_uid" json:"tempo_datasource_uid" minLength:"1"`
	DeploymentEnvironment string `mapstructure:"deployment_environment" json:"deployment_environment" minLength:"1"`
}

type LangfuseSearchSettings struct {
	BaseURL                          string `mapstructure:"base_url" json:"base_url" format:"uri"`
	ProjectID                        string `mapstructure:"project_id" json:"project_id" minLength:"1"`
	SandboxNamespaceMetadataKey      string `mapstructure:"sandbox_namespace_metadata_key" json:"sandbox_namespace_metadata_key" minLength:"1"`
	SandboxServiceAccountMetadataKey string `mapstructure:"sandbox_service_account_metadata_key" json:"sandbox_service_account_metadata_key" minLength:"1"`
}

func (c FrontendConfig) validate() error {
	required := map[string]string{}
	if trace := c.TraceSearch; trace != nil {
		if err := validateHTTPSURL("frontend_config.trace_search.grafana_base_url", trace.GrafanaBaseURL); err != nil {
			return err
		}
		required["frontend_config.trace_search.tempo_datasource_uid"] = trace.TempoDatasourceUID
		required["frontend_config.trace_search.deployment_environment"] = trace.DeploymentEnvironment
	}
	if langfuse := c.LangfuseSearch; langfuse != nil {
		if err := validateHTTPSURL("frontend_config.langfuse_search.base_url", langfuse.BaseURL); err != nil {
			return err
		}
		required["frontend_config.langfuse_search.project_id"] = langfuse.ProjectID
		required["frontend_config.langfuse_search.sandbox_namespace_metadata_key"] = langfuse.SandboxNamespaceMetadataKey
		required["frontend_config.langfuse_search.sandbox_service_account_metadata_key"] = langfuse.SandboxServiceAccountMetadataKey
	}
	for name, value := range required {
		if value == "" {
			return fmt.Errorf("%s must not be empty", name)
		}
	}
	return nil
}

func validateHTTPSURL(name, raw string) error {
	if err := validateHTTPURL(name, raw); err != nil {
		return err
	}
	parsed, _ := url.Parse(raw)
	if parsed.Scheme != "https" {
		return fmt.Errorf("%s must use HTTPS", name)
	}
	return nil
}

package controller

import (
	"context"
	"testing"

	appsv1alpha1 "carewright.io/carewright-operator/api/v1alpha1"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

func TestWorkflowAPIBaseURL(t *testing.T) {
	tests := []struct {
		name, address, want string
	}{
		{"published route", "https://workflow.example.test/wcpgingesterworkflow", "https://workflow.example.test"},
		{"in-cluster service", "http://workflow.default.svc.cluster.local:80", "http://workflow.default.svc.cluster.local:80"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := workflowAPIBaseURL(test.address); got != test.want {
				t.Errorf("workflowAPIBaseURL(%q) = %q, want %q", test.address, got, test.want)
			}
		})
	}
}

func TestIngesterWriterWatchMapping(t *testing.T) {
	scheme := runtime.NewScheme()
	if err := appsv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	matching := &appsv1alpha1.CPGIngester{
		ObjectMeta: metav1.ObjectMeta{Name: "matching", Namespace: "pipelines"},
		Spec:       appsv1alpha1.CPGIngesterSpec{CarePlanWriterRef: &appsv1alpha1.PipelineReference{Name: "writer"}},
	}
	other := &appsv1alpha1.CPGIngester{
		ObjectMeta: metav1.ObjectMeta{Name: "other", Namespace: "pipelines"},
		Spec:       appsv1alpha1.CPGIngesterSpec{CarePlanWriterRef: &appsv1alpha1.PipelineReference{Name: "another-writer"}},
	}
	reconciler := &CPGIngesterReconciler{Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(matching, other).Build()}
	writer := &appsv1alpha1.CarePlanWriter{ObjectMeta: metav1.ObjectMeta{Name: "writer", Namespace: "pipelines"}}
	requests := reconciler.ingestersForWriter(context.Background(), writer)
	if len(requests) != 1 || requests[0].NamespacedName.Namespace != "pipelines" || requests[0].NamespacedName.Name != "matching" {
		t.Fatalf("unexpected CPGIngester requests for writer: %+v", requests)
	}
}

func TestPipelineComponentContracts(t *testing.T) {
	find := func(components []sandboxComponent, name string) sandboxComponent {
		t.Helper()
		for _, component := range components {
			if component.Name == name {
				return component
			}
		}
		t.Fatalf("component %q not found", name)
		return sandboxComponent{}
	}
	checkAccess := func(component sandboxComponent, name, host string) {
		t.Helper()
		for _, access := range component.NetworkAccess {
			if access.Name == name && access.Host == host && access.Port == 443 {
				return
			}
		}
		t.Errorf("%s lacks %s egress to %s: %+v", component.Name, name, host, component.NetworkAccess)
	}

	ingester := &appsv1alpha1.CPGIngester{ObjectMeta: metav1.ObjectMeta{Name: "ingester", Namespace: "pipelines"}}
	ingesterComponents := cpgIngesterComponents(ingester, map[string]string{"bff": "https://ingester-bff.example.test"}, "https://workflow.example.test/wingesterworkflow", "https://writer-bff.example.test")
	ingesterBFF := find(ingesterComponents, "bff")
	if ingesterBFF.Env["SONATAFLOW_URL"] != "https://workflow.example.test" || ingesterBFF.Env["SONATAFLOW_WORKFLOW_NAME"] != "wingesterworkflow" || ingesterBFF.Env["ACP_WRITER_BFF_URL"] != "https://writer-bff.example.test" {
		t.Errorf("incorrect CPG BFF workflow and writer inputs: %+v", ingesterBFF.Env)
	}
	checkAccess(find(ingesterComponents, "ui"), "bff", "ingester-bff.example.test")

	writer := &appsv1alpha1.CarePlanWriter{ObjectMeta: metav1.ObjectMeta{Name: "writer", Namespace: "pipelines"}}
	writerComponents := carePlanWriterComponents(writer, map[string]string{
		"bff": "https://writer-bff.example.test", "llm-reasoning": "https://reasoning.example.test",
		"decision-engine": "https://decision.example.test", "decision-service": "https://dmn.example.test",
		"fhir-server": "https://fhir.example.test",
	}, "https://workflow.example.test/wwriterworkflow")
	writerBFF := find(writerComponents, "bff")
	if writerBFF.Env["SONATAFLOW_URL"] != "https://workflow.example.test" || writerBFF.Env["SONATAFLOW_WORKFLOW_NAME"] != "wwriterworkflow" {
		t.Errorf("incorrect writer BFF workflow inputs: %+v", writerBFF.Env)
	}
	checkAccess(find(writerComponents, "ui"), "bff", "writer-bff.example.test")
	checkAccess(writerBFF, "llm-reasoning", "reasoning.example.test")
	checkAccess(writerBFF, "decision-engine", "decision.example.test")
	checkAccess(writerBFF, "fhir-server", "fhir.example.test")
	checkAccess(find(writerComponents, "llm-reasoning"), "decision-engine", "decision.example.test")
	checkAccess(find(writerComponents, "decision-engine"), "decision-service", "dmn.example.test")
	checkAccess(find(writerComponents, "mcp"), "decision-service", "dmn.example.test")
	checkAccess(find(writerComponents, "mcp"), "fhir-server", "fhir.example.test")
}

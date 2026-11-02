import streamlit as st

from application.dashboard_ui import page_header


def render():
    page_header(
        "Self-healing Workflow Foundation",
        "Remediation center",
        "A reserved control-center area for future policy and workflow visibility.",
    )
    st.info(
        "Remediation is not implemented. This page does not execute actions, request approvals, "
        "or create remediation records."
    )

    columns = st.columns(5)
    columns[0].metric("Policy mode", "Not configured")
    columns[1].metric("Execution classification", "Not configured")
    columns[2].metric("Dry run", "Not available")
    columns[3].metric("Approval workflow", "Not implemented")
    columns[4].metric("Execution records", "Not available")

    st.subheader("Proposed remediation actions")
    st.info("No approved remediation policy or action catalog is configured. No action can be selected or executed.")

    workflow_cols = st.columns(3)
    with workflow_cols[0]:
        with st.container(border=True):
            st.markdown("**Approval workflow**")
            st.write("Pending implementation")
            st.caption("No approval controls are active.")
    with workflow_cols[1]:
        with st.container(border=True):
            st.markdown("**Execution history**")
            st.write("Pending implementation")
            st.caption("No remediation execution endpoint exists.")
    with workflow_cols[2]:
        with st.container(border=True):
            st.markdown("**Post-action verification**")
            st.write("Pending implementation")
            st.caption("No remediation health verification is available.")

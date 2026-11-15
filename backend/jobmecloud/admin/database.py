"""Create or update the tables in the deployed Aurora DSQL cluster."""

from jobmecloud.admin.stack import stack_outputs
from jobmecloud.db.engine import make_engine as default_make_engine
from jobmecloud.db.migrate import migrate as default_migrate


def migrate_deployed(stack_name: str, *, make_engine=default_make_engine, migrate=default_migrate, cfn=None) -> list[str]:
    """Run with admin AWS credentials: the connection signs in as the cluster's admin role."""
    endpoint = stack_outputs(stack_name, cfn)["DatabaseEndpoint"]
    engine = make_engine(f"dsql://{endpoint}")
    try:
        return migrate(engine)
    finally:
        engine.dispose()

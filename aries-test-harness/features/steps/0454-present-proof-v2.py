from behave import *
import json
from agent_backchannel_client import agent_backchannel_POST, expected_agent_state
from agent_test_utils import get_relative_timestamp_to_epoch, amend_presentation_definition_with_runtime_data


@given('"{prover}" has an issued credential with formats from {issuer} with {credential_data}')
def step_impl(context, prover, issuer, credential_data):
    #assign the credential data to the context for use in the credential offer or proposal. 
    if credential_data != None:
        if "schema_dict" in context:
            for schema in context.schema_dict:
                if 'credential_data_dict' in context:
                    try:
                        credential_data_json_file = open('features/data/cred_data_' + schema.lower() + '.json')
                        context.credential_data_dict[schema] = json.load(credential_data_json_file)[credential_data]['attributes']
                    except FileNotFoundError:
                        print(FileNotFoundError + ': features/data/cred_data_' + schema.lower() + '.json')
                else:
                    try:
                        credential_data_json_file = open('features/data/cred_data_' + schema.lower() + '.json')
                        context.credential_data_dict = {schema: json.load(credential_data_json_file)[credential_data]['attributes']}
                    except FileNotFoundError:
                        print(FileNotFoundError + ': features/data/cred_data_' + schema.lower() + '.json')

    # Check if a connection between the players has already been established in this test. 
    if prover not in context.connection_id_dict or issuer not in context.connection_id_dict[prover]:
        context.execute_steps('''
            Given "''' + issuer + '''" and "''' + prover + '''" have an existing connection
        ''')

    # Set the cred format from the feature tags.
    # TODO Check of the Prefix CredFormat exists, throw and error if not. It is mandatory
    if "CredFormat_Indy" in context.tags:
        context.current_cred_format = "indy"
    elif "CredFormat_JSON-LD" in context.tags:
        context.current_cred_format = "json-ld"

    # make sure the issuer has the credential definition
    # If there is a schema_dict then we are working with multiple credential types, loop as many times as 
    # there are schemas and add the schema to context as the issue cred tests expect. 
    if 'schema_dict' not in context:
        # Schema not defined in feature file. use @SchemaName as a feature tag that points to a corresponding file
        raise Exception('Schema not tagged in Feature File Scenario. Use @SchemaName as a feature tag that points to a corresponding file.')
    else:
        for schema in context.schema_dict:
            context.support_revocation = context.support_revocation_dict[schema]
            context.schema = context.schema_dict[schema]
            context.execute_steps(f'''
                Given "{issuer}" is ready to issue a "{context.current_cred_format}" credential
            ''')

        # setup the holder and issuer for the issue cred scenario below. The data table in the tests does not setup a holder.
        # The prover is also the holder.
        context.holder_url = context.config.userdata.get(prover)
        context.holder_name = prover
        assert context.holder_url is not None and 0 < len(context.holder_url)
        # The issuer was not in the data table, it was in the gherkin scenario outline examples, so get it and assign it.
        context.issuer_url = context.config.userdata.get(issuer)
        context.issuer_name = issuer
        assert context.issuer_url is not None and 0 < len(context.issuer_url)

        # issue the credential to prover
        # If there is a schema_dict then we are working with mulitple credential types, loop as many times as 
        # there are schemas and add the schema to context as the issue cred tests expect. 
        if "CredProposalStart" in context.tags:
            context_steps_start = f'''
                When  "{prover}" proposes a "{context.current_cred_format}" credential to "{issuer}" with {credential_data}
                And '''
        else:
            context_steps_start = f'''
                When '''
        for schema in context.schema_dict:
            context.credential_data = context.credential_data_dict[schema]
            context.schema = context.schema_dict[schema]
            context_steps = context_steps_start + f''' "{issuer}" offers the "{context.current_cred_format}" credential
                And "{prover}" requests the "{context.current_cred_format}" credential
                And  "{issuer}" issues the "{context.current_cred_format}" credential
                And "{prover}" acknowledges the "{context.current_cred_format}" credential issue
                Then "{prover}" has the "{context.current_cred_format}" credential issued
            '''
            context.execute_steps(context_steps)


@when('"{verifier}" sends a {request_for_proof} presentation with formats to "{prover}"')
def step_impl(context, verifier, request_for_proof, prover):
    try:
        request_for_proof_json_file = open('features/data/' + request_for_proof + '.json')
        request_for_proof_json = json.load(request_for_proof_json_file)
        context.request_for_proof = request_for_proof_json["presentation_proposal"]

    except FileNotFoundError:
        print(FileNotFoundError + ': features/data/' + request_for_proof + '.json')

    # check for a schema template already loaded in the context. If it is, it was loaded from an external Schema, so use it.
    if "request_for_proof" in context:
        data = context.request_for_proof

        if context.current_cred_format == "indy":
            if "non_revoked_timeframe" in context:
                data["non_revoked"] = context.non_revoked_timeframe["non_revoked"]

        elif context.current_cred_format == "json-ld":
            data = amend_presentation_definition_with_runtime_data(context, data)
        else:
            raise Exception(f"Unknown cred format {context.current_cred_format}")

    presentation_proposal = {
        "presentation_proposal": {
            "format": context.current_cred_format,
            "comment": "This is a comment for the request for presentation.",
            "data":  data
        }
    }

    if ('connectionless' in context) and (context.connectionless == True):
        (resp_status, resp_text) = agent_backchannel_POST(context.verifier_url + "/agent/command/", "proof-v2", operation="create-send-connectionless-request", data=presentation_proposal)
    else:
        presentation_proposal["presentation_proposal"]["connection_id"] = context.connection_id_dict[verifier][prover]

        # send presentation request
        (resp_status, resp_text) = agent_backchannel_POST(context.verifier_url + "/agent/command/", "proof-v2", operation="send-request", data=presentation_proposal)
    
    assert resp_status == 200, f'resp_status {resp_status} is not 200; {resp_text}'
    resp_json = json.loads(resp_text)
    # check the state of the presentation from the verifiers perspective
    assert resp_json["state"] == "request-sent"

    # save off anything that is returned in the response to use later?
    context.presentation_thread_id = resp_json["thread_id"]

    # check the state of the presentation from the provers perspective
    # if the protocol is connectionless then don't do this, the prover has not recieved anything yet.
    if ('connectionless' not in context) or (context.connectionless == False):
        assert expected_agent_state(context.prover_url, "proof-v2", context.presentation_thread_id, "request-received")
    else:
        # save off the presentation exchange id for use when the prover sends the presentation with a service decorator
        context.presentation_exchange_id = resp_json["presentation_exchange_id"]



@when('"{prover}" makes the {presentation} of the proof with formats')
def step_impl(context, prover, presentation):
    # Open the presentation json file
    try:
        presentation_json_file = open('features/data/' + presentation + '.json')
        presentation_json = json.load(presentation_json_file)
        context.presentation = presentation_json["presentation"]

    except FileNotFoundError:
        print(FileNotFoundError + ': features/data/' + presentation + '.json')

    prover_url = context.prover_url

    if "presentation" in context:
        presentation = context.presentation

        if context.current_cred_format == "indy":
            # Find the cred ids and add the actual cred id into the presentation
            # TODO: There is probably a better way to get access to the specific requested attributes and predicates. Revisit this later.
            try:
                for i in range(json.dumps(presentation["requested_attributes"]).count("cred_id")):
                    # Get the schema name from the loaded presentation for each requested attributes
                    cred_type_name = presentation["requested_attributes"][list(presentation["requested_attributes"])[i]]["cred_type_name"]
                    presentation["requested_attributes"][list(presentation["requested_attributes"])[i]]["cred_id"] = context.credential_id_dict[cred_type_name][len(context.credential_id_dict[cred_type_name])-1]
                    # If there is a timestamp, calculate it from the instruction in the file. Can be 'now' or + - relative to now.
                    if ("timestamp" in presentation["requested_attributes"][list(presentation["requested_attributes"])[i]]):
                        relative_timestamp = presentation["requested_attributes"][list(presentation["requested_attributes"])[i]]["timestamp"]
                        presentation["requested_attributes"][list(presentation["requested_attributes"])[i]]["timestamp"] = get_relative_timestamp_to_epoch(relative_timestamp)
                    # Remove the cred_type_name from this part of the presentation since it won't be needed in the actual request.
                    presentation["requested_attributes"][list(presentation["requested_attributes"])[i]].pop("cred_type_name")
            except KeyError:
                pass
            
            try:
                for i in range(json.dumps(presentation["requested_predicates"]).count("cred_id")):
                    # Get the schema name from the loaded presentation for each requested predicates
                    cred_type_name = presentation["requested_predicates"][list(presentation["requested_predicates"])[i]]["cred_type_name"]
                    presentation["requested_predicates"][list(presentation["requested_predicates"])[i]]["cred_id"] = context.credential_id_dict[cred_type_name][len(context.credential_id_dict[cred_type_name])-1] 
                    # If there is a timestamp, calculate it from the instruction in the file. Can be 'now' or + - relative to now.
                    if ("timestamp" in presentation["requested_predicates"][list(presentation["requested_predicates"])[i]]):
                        relative_timestamp = presentation["requested_predicates"][list(presentation["requested_predicates"])[i]]["timestamp"]
                        presentation["requested_predicates"][list(presentation["requested_predicates"])[i]]["timestamp"] = get_relative_timestamp_to_epoch(relative_timestamp)
                    # Remove the cred_type_name from this part of the presentation since it won't be needed in the actual request.
                    presentation["requested_predicates"][list(presentation["requested_predicates"])[i]].pop("cred_type_name")
            except KeyError:
                pass

        elif context.current_cred_format == "json-ld":
            # All good
            cred_type_name = presentation.get("cred_type_name")
            record_ids = presentation.get("record_ids", {})

            new_record_ids = {}
            for (input_descriptor_id, record_ids) in record_ids.items():
                new_record_ids[input_descriptor_id] = [context.credential_id_dict[cred_type_name][-1] for cred_type_name in record_ids]
            
            presentation["record_ids"] = new_record_ids
        else:
            raise Exception(f"Unknown format {context.current_cred_format}")


        presentation["format"] = context.current_cred_format

    # if this is happening connectionless, then add the service decorator to the presentation
    if ('connectionless' in context) and (context.connectionless == True):
        presentation["~service"] = {
                "recipientKeys": [
                    context.presentation_exchange_id
                ],
                "routingKeys": None,
                "serviceEndpoint": context.verifier_url
            }

    (resp_status, resp_text) = agent_backchannel_POST(prover_url + "/agent/command/", "proof-v2", operation="send-presentation", id=context.presentation_thread_id, data=presentation)
    assert resp_status == 200, f'resp_status {resp_status} is not 200; {resp_text}'
    resp_json = json.loads(resp_text)
    assert resp_json["state"] == "presentation-sent"

    # check the state of the presentation from the verifier's perspective
    assert expected_agent_state(context.verifier_url, "proof-v2", context.presentation_thread_id, "presentation-received")


@when('"{verifier}" acknowledges the proof with formats')
def step_impl(context, verifier):
    verifier_url = context.verifier_url

    (resp_status, resp_text) = agent_backchannel_POST(verifier_url + "/agent/command/", "proof-v2", operation="verify-presentation", id=context.presentation_thread_id)
    assert resp_status == 200, f'resp_status {resp_status} is not 200; {resp_text}'
    resp_json = json.loads(resp_text)
    assert resp_json["state"] == "done"

    if "support_revocation" in context:
        if context.support_revocation:
            # Add the verified property returned to the credential verification dictionary to check in subsequent steps. Key by presentation thread id
            if "credential_verification_dict" in context:
                context.credential_verification_dict[context.presentation_thread_id] = resp_json["verified"]
            else:
                context.credential_verification_dict = {context.presentation_thread_id: resp_json["verified"]}

@then('"{prover}" has the proof with formats verified')
def step_impl(context, prover):
    # check the state of the presentation from the prover's perspective
    assert expected_agent_state(context.prover_url, "proof-v2", context.presentation_thread_id, "done")

    # Check the status of the verification in the verify-presentation call. Should be True
    if 'credential_verification_dict' in context:
        assert context.credential_verification_dict[context.presentation_thread_id] == "true"
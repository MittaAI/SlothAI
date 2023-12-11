# complete dictionaries
def ai_csv_headers(model="gpt-3.5-turbo-1106", prompt="", retries=3):
    # negotiate the format
    if model == "gpt-3.5-turbo-1106" and "JSON" in prompt:
        system_content = "Looking at an example, output a JSON list of header strings for the rows in a CSV."
        response_format = {'type': "json_object"}
    else:
        system_content = "Looking at an example, output a JSON list of header strings for the rows in a CSV. Only output a JSON list, nothing more."
        response_format = None

    # try a few times
    for _try in range(retries):
        completion = openai.chat.completions.create(
            model = model,
            response_format = response_format,
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt}
            ]
        )
        ai_array_str = completion.choices[0].message.content.replace("\n", "").replace("\t", "")
        ai_array_str = re.sub(r'\s+', ' ', ai_array_str).strip()

        try:
            ai_array = eval(ai_array_str)
            err = None
            break
        except (ValueError, SyntaxError, NameError, AttributeError, TypeError) as ex:
            ai_array = []
            err = f"AI returned a un-evaluatable, non-array object on try {_try} of {retries}: {ex}"
            time.sleep(2) # give it a few seconds

    return err, ai_array
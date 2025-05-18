def search_truepeoplesearch(context, address: str, debug: bool, inspect: bool) -> List[Dict[str, object]]:
    if debug:
        print("Trying TruePeopleSearch...")

    page = context.new_page()
    apply_stealth(page)
    page.goto("https://www.truepeoplesearch.com/", wait_until="domcontentloaded", timeout=30000)

    try:
        page.click("a[href*='Address']", timeout=5000)
    except Exception:
        if debug:
            print("Failed to click Address tab")

    try:
        address_input = page.locator("input[placeholder*='City']").first
        address_input.wait_for(timeout=5000)
        address_input.type(address, delay=75)
    except Exception:
        if debug:
            print("Failed to locate or type into address input field")
        html = page.content()
        if debug:
            save_debug_html(html)
        page.close()
        return []

    try:
        page.click("button[type='submit']")
    except Exception:
        try:
            page.keyboard.press("Enter")
        except Exception:
            if debug:
                print("Failed to submit address search")
            page.close()
            return []

    page.wait_for_load_state("domcontentloaded")
    html = page.content()
    if debug:
        save_debug_html(html)

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card a[href*='/details']")
    if debug:
        print(f"Found {len(cards)} cards on TruePeopleSearch")
    if inspect:
        for card in cards:
            print("TPS card:\n", card.get_text(" ", strip=True))

    results = []
    for link in cards:
        href = link.get("href")
        if not href:
            continue
        detail_url = href if href.startswith("http") else f"https://www.truepeoplesearch.com{href}"
        detail_html = fetch_html(context, detail_url, debug)
        detail_soup = BeautifulSoup(detail_html, "html.parser")
        name_el = detail_soup.find(["h1", "h2", "strong"])
        name = name_el.get_text(strip=True) if name_el else ""
        loc_el = detail_soup.find(string=re.compile("Current Address", re.I))
        if loc_el and loc_el.find_parent("div"):
            location_div = loc_el.find_parent("div").find_next_sibling("div")
            location = location_div.get_text(strip=True) if location_div else ""
        else:
            location = ""
        phones = _parse_phones(detail_soup.get_text(" "))
        if name or phones:
            results.append({
                "name": name,
                "phones": phones,
                "city_state": location,
                "source": "TruePeopleSearch",
            })
    page.close()
    return results

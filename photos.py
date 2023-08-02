#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import choice
from subprocess import check_call
from typing import Any, Optional
from xml.etree import ElementTree

from jinja2 import Environment, FileSystemLoader
from picpocket import load
from picpocket.parsing import full_path
from PIL import Image

DEFAULT_DIRECTORY = Path.home() / ".config" / "picpocket"


SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    image INTEGER PRIMARY KEY,
    date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    tag TEXT PRIMARY KEY,
    display BOOL NOT NULL
);
"""

DIRECTORY = Path(__file__).absolute().parent
ADJECTIVES = DIRECTORY / "adjectives.txt"
NOUNS = DIRECTORY / "birds.txt"
TEMPLATES_DIRECTORY = DIRECTORY / "templates"
ENVIRONMENT = Environment(loader=FileSystemLoader(TEMPLATES_DIRECTORY))

ATOM_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
RSS_DATE_FORMAT = '%a, %d %b %Y %H:%M:%S -0000'
COMMENT_DATE_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class Page:
    relative: str
    template: str
    title: str
    arguments: dict[str, Any]
    date: Optional[datetime] = None
    section: bool = False
    environment: Environment = ENVIRONMENT

    def render(
        self,
        root: Path,
        navbar: Optional[tuple[str, str]] = None,
        users: Optional[dict[str, str]] = None,
        domain: Optional[str] = None
    ):
        template = self.environment.get_template(self.template)
        path = root / self.relative

        path.parent.mkdir(exist_ok=True)

        if "/" in self.relative:
            path_to_root = "/".join([".."] * self.relative.count("/"))
        else:
            path_to_root = "."

        try:
            with path.open("w") as stream:
                stream.write(
                    template.render(
                        page_title=self.title,
                        path_to_root=path_to_root,
                        **self.arguments,
                        navbar=navbar,
                        users=users,
                        domain=domain,
                    )
                )
        except Exception as exception:
            print(f"building {self.relative} failed: {exception!r}")

    def render_feeds(self, site: str, root: Path, pages: Page):
        directory = Path(self.relative).parent

        url_base = f"https://{site}"

        now = datetime.utcnow().astimezone()

        atom_url = f"{directory}/atom.xml"
        rss_url = f"{directory}/rss.xml"

        atom_root = ElementTree.Element(
            "feed", attrib={"version": "1.0", "xmlns": "http://www.w3.org/2005/Atom"}
        )
        rss_root = ElementTree.Element(
            "rss", attrib={"version": "2.0", }
        )

        rss_channel = ElementTree.SubElement(rss_root, "channel")

        ElementTree.SubElement(atom_root, "id").text = f"{site}/{self.title}"
        ElementTree.SubElement(atom_root, "title").text = self.title
        ElementTree.SubElement(rss_channel, "title").text = self.title
        ElementTree.SubElement(atom_root, "updated").text = now.strftime(
            ATOM_DATE_FORMAT
        )
        ElementTree.SubElement(
            rss_channel, "lastBuildDate"
        ).text = now.strftime(RSS_DATE_FORMAT)
        ElementTree.SubElement(
            ElementTree.SubElement(atom_root, "author"), "name"
        ).text = "bcj"
        ElementTree.SubElement(rss_channel, "link").text = f"{url_base}/{directory}"
        ElementTree.SubElement(
            atom_root, "link", attrib={"rel": "self", "href": atom_url}
        )
        ElementTree.SubElement(
            atom_root,
            "link",
            attrib={"rel": "alternate", "href": f"https://{site}/{directory}"},
        )
        ElementTree.SubElement(atom_root, "link").text = f"https://{site}/{directory}"

        # TODO: categories
        # ElementTree.SubElement(atom_root, "category", attrib={"term": category})
        # ElementTree.SubElement(rss_channel, "category").text = category

        if "description" in self.arguments:
            description = self.arguments["description"]
            ElementTree.SubElement(atom_root, "subtitle").text = description
            ElementTree.SubElement(rss_channel, "description").text = description
        else:
            ElementTree.SubElement(rss_channel, "description").text = "..."

        for page in sorted(pages, key=lambda page: page.date, reverse=True):
            entry = ElementTree.SubElement(atom_root, "entry")
            item = ElementTree.SubElement(rss_channel, "item")

            post_url = f"https://{site}/{page.relative}"
            post_description = page.arguments.get("description") or ""
            ElementTree.SubElement(entry, "id").text = post_url
            ElementTree.SubElement(item, "guid").text = post_url
            ElementTree.SubElement(entry, "title").text = page.title
            published = page.date.strftime(ATOM_DATE_FORMAT)
            ElementTree.SubElement(entry, "published").text = published
            ElementTree.SubElement(entry, "updated").text = published
            ElementTree.SubElement(item, "pubDate").text = page.date.strftime(
                RSS_DATE_FORMAT
            )
            ElementTree.SubElement(
                entry, "content", attrib={"type": "html"}
            ).text = page.render_entry(site)
            num_images = len(page.arguments["images"])
            if num_images > 1:
                ElementTree.SubElement(item, "title").text = " ".join(
                    (page.title, f"({num_images} images)")
                )
            else:
                ElementTree.SubElement(item, "title").text = page.title
            image_info = page.arguments["images"][0]
            image_path = root / "images" / image_info["file"]
            with image_path.open("rb") as stream:
                length = len(stream.read())
            mime = Image.open(image_path).get_format_mimetype()

            ElementTree.SubElement(
                item,
                "enclosure",
                attrib={
                    "url": f"https://{site}/images/{image_info['file']}",
                    "length": str(length),
                    "type": mime,
                }
            )
            ElementTree.SubElement(
                entry,
                "link",
                attrib={"rel": "alternate", "href": post_url},
            )
            ElementTree.SubElement(item, "link").text = post_url
            ElementTree.SubElement(entry, "summary").text = post_description
            ElementTree.SubElement(item, "description").text = post_description

        ElementTree.ElementTree(atom_root).write(root / atom_url)
        ElementTree.ElementTree(rss_root).write(root / rss_url)

    def render_entry(self, site: str) -> str:
        template = self.environment.get_template("minimal.html")
        return template.render(
            page_title=self.title, path_to_root=f"https://{site}", **self.arguments
        )


def main():
    parser = ArgumentParser(description="A static site generator for photos")
    parser.add_argument("domain", help="the domain to host photos on")
    parser.add_argument(
        "--config",
        default=DEFAULT_DIRECTORY,
        type=full_path,
        help="Your PicPocket config directory"
    )

    subparsers = parser.add_subparsers(dest="command", help="Run the generator")

    initialize = subparsers.add_parser("initialize", help="Configure the site")
    initialize.add_argument("build", type=full_path, help="Where to build the site")
    initialize.add_argument("--name", help="The name of the site")
    initialize.add_argument("--favicon", type=full_path, help="The site favicon")

    create_auto = subparsers.add_parser(
        "create-auto",
        help="Create a blog that adds all images matching a set of criteria"
    )
    create_auto.add_argument("title", help="The title of the section")
    create_auto.add_argument("--slug", help="The url slug of the section")
    create_auto.add_argument("--description", help="The description of the section")
    create_auto.add_argument(
        "--creators", nargs="+", help="Only include images with these creators"
    )
    create_auto.add_argument(
        "--min-rating", type=int, help="The minimum image rating to include"
    )
    create_auto.add_argument(
        "--all-tags", nargs="+", help="Only match images with these tags"
    )
    create_auto.add_argument(
        "--no-tags", nargs="+", help="Only match images with none of these tags"
    )
    create_auto.add_argument("--icon", help="The symbol to use in menus")

    create_blog = subparsers.add_parser(
        "create-blog",
        help="Create a blog that adds manually curated photos"
    )
    create_blog.add_argument("title", help="The title of the section")
    create_blog.add_argument("--slug", help="The url slug of the section")
    create_blog.add_argument("--description", help="The description of the section")
    create_blog.add_argument("--icon", help="The symbol to use in menus")

    blog_post = subparsers.add_parser("post", help="Create a new post")
    blog_post.add_argument("blog", help="The slug of the blog to add the post to")
    blog_post.add_argument("title", help="The name of the blog")
    blog_post.add_argument("--slug", help="The slug for the blog post")
    blog_post.add_argument("--description", help="The text of the blog post")
    blog_post.add_argument("--images", nargs="+", type=int, help="The images to attach")
    blog_post.add_argument(
        "--date",
        dest="timestamp",
        type=parse_date,
        help="The date of the post in 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD' format"
    )

    add_user = subparsers.add_parser("add-user", description="Add a user")
    add_user.add_argument("email", help="The user's email")
    add_user.add_argument("--display", help="The user's display name")

    add_comment = subparsers.add_parser("add-comment", description="Add a comment")
    add_comment.add_argument("email", help="The user")
    blog_section = add_comment.add_mutually_exclusive_group()
    blog_section.add_argument("--blog", help="The name of the blog")
    blog_section.add_argument("--section", help="The name of the section")
    add_comment.add_argument("--slug", required=True, help="The slug")
    add_comment.add_argument("comment", help="The comment")

    build = subparsers.add_parser("build", help="Build your website")
    build.add_argument("--fresh", action="store_true", help="Delete existing files")

    args = parser.parse_args()

    with asyncio.Runner() as runner:
        runner.run(run(args))


async def run(args):
    if not args.config.is_dir():
        print(f"Unknown PicPocket: config directory: {args.config}")
        exit(1)

    directory = args.config / f"site-{args.domain}"
    config = directory / "config.json"
    database = directory / "db.sqlite3"
    user_file = directory / "users.json"

    if args.command == "initialize":
        if directory.exists():
            print("Configuration already exists for site")
            exit(1)

        directory.mkdir()
        data = {
            "build": str(args.build.absolute()),
            "colours": {
                "light": {
                    "background": {
                        "page": "#397367",
                        "article": "#C1DCEB",
                    },
                    "text": {
                        "text": "#0E1B18",
                        "accent": "#613F75",
                        "link": "#4D053D",
                    }
                },
                "dark": {
                    "background": {
                        "page": "#0E1B18",
                        "article": "#142F3E",
                    },
                    "text": {
                        "text": "#FDD8F5",
                        "accent": "#F7D3A1",
                        "link": "#D7EADF",
                    }
                },
            },
            "name": args.name or args.domain,
        }

        if args.favicon:
            favicon = directory / args.favicon.name
            shutil.copy2(args.favicon, favicon)
            data["favicon"] = favicon.name

        with config.open("w") as stream:
            json.dump(data, stream, indent=4, sort_keys=True)

        args.build.mkdir(exist_ok=True, parents=True)

        connection = sqlite3.connect(database)
        connection.executescript(SCHEMA)
        connection.commit()
        print("Site initialized")
    elif not directory.is_dir():
        print("Site configuration doesn't exist")
        exit(1)
    elif args.command == "create-auto":
        if args.slug is None:
            parts = []
            for symbol in args.title:
                if symbol.isalpha() and symbol.isascii():
                    parts.append(symbol.lower())
                elif parts and parts[-1] != "-":
                    parts.append("-")

            args.slug = "".join(parts)

        if args.slug in ("images", "tags"):
            print(f"illegal slug: {args.slug}")
            exit(1)

        section_config = directory / f"section-{args.slug}.json"
        if section_config.exists():
            print(f"Configuration already exists: {section_config}")
            exit(1)

        with section_config.open("w") as stream:
            json.dump(
                {
                    "title": args.title,
                    "slug": args.slug,
                    "description": args.description,
                    "creators": args.creators,
                    "min-rating": args.min_rating,
                    "all-tags": args.all_tags,
                    "no-tags": args.no_tags,
                    "icon": args.icon,
                },
                stream,
                indent=4,
                sort_keys=True,
            )
        print("Section added")
    elif args.command == "create-blog":
        if args.slug is None:
            parts = []
            for symbol in args.title:
                if symbol.isalpha() and symbol.isascii():
                    parts.append(symbol.lower())
                elif parts and parts[-1] != "-":
                    parts.append("-")

            args.slug = "".join(parts)

        if args.slug in ("images", "tags"):
            print(f"illegal slug: {args.slug}")
            exit(1)

        section_directory = directory / f"blog-{args.slug}"

        if section_directory.exists():
            print(f"Configuration already exists: {section_directory}")
            exit(1)

        section_directory.mkdir()

        section_config = section_directory / "config.json"
        with section_config.open("w") as stream:
            json.dump(
                {
                    "title": args.title,
                    "slug": args.slug,
                    "description": args.description,
                    "icon": args.icon,
                },
                stream,
                indent=4,
                sort_keys=True,
            )
        print("Section added")
    elif args.command == "post":
        if args.timestamp is None:
            args.timestamp = int(datetime.now().timestamp())

        blog_directory = directory / f"blog-{args.blog}"

        if not blog_directory.exists():
            print(f"unknown blog: {args.blog}")
            exit(1)

        if args.slug is None:
            args.slug = str(args.timestamp)

        post_config = blog_directory / f"{args.timestamp}.json"

        post_data = {
            "title": args.title,
            "slug": args.slug,
            "description": args.description,
            "images": args.images,
        }

        api = load(args.config)
        for image_id in args.images:
            image = await api.get_image(image_id)

            if image is None:
                print(f"unknown image: {image_id}")
                exit(1)

        with post_config.open("w") as stream:
            json.dump(post_data, stream, indent=4, sort_keys=True)

        print("post configured")

    elif args.command == "add-user":
        if user_file.exists():
            with user_file.open("r") as stream:
                user_data = json.load(stream)
        else:
            user_data = {}

        if args.email in user_data:
            print(f"user {args.email} already exists")
            exit(1)

        if args.display is None:
            with ADJECTIVES.open("r") as stream:
                adjectives = list(stream.read().splitlines())

            with NOUNS.open("r") as stream:
                nouns = list(stream.read().splitlines())

            while args.display is None:
                display = " ".join((choice(adjectives), choice(nouns)))

                if display in user_data.values():
                    continue

                response = input(f"name: {display}? y/n\n")
                if response == "y":
                    args.display = display
        elif args.display in user_data.values():
            print(f"display name {args.display} already taken")
            exit(1)

        user_data[args.email] = args.display

        with user_file.open("w") as stream:
            json.dump(user_data, stream, sort_keys=True, indent=4)

        print("user added")
    elif args.command == "add-comment":
        if not user_file.exists():
            print("user file doesn't exist")
            exit(1)

        with user_file.open("r") as stream:
            user_data = json.load(stream)

        if args.email not in user_data:
            print(f"unknown user: {args.email}")
            exit(1)

        if args.section:
            section_file = directory / f"section-{args.section}.json"
        elif args.blog:
            section_file = directory / args.blog / "config.json"
        else:
            print("supply a blog or section")
            exit(1)

        if not section_file.exists():
            print(f"unknown section: {section_file.stem}")
            exit(1)

        with section_file.open("r") as stream:
            data = json.load(stream)

        if "comments" not in data:
            data["comments"] = {}

        if args.slug not in data["comments"]:
            data["comments"][args.slug] = []

        data["comments"][args.slug].append([args.email, args.comment])

        with section_file.open("w") as stream:
            json.dump(data, stream, indent=4, sort_keys=True)
    elif args.command == "build":
        with config.open("r") as stream:
            data = json.load(stream)

        build = Path(data["build"])

        if args.fresh and build.exists():
            shutil.rmtree(build)

        build.mkdir(exist_ok=True, parents=True)

        if "favicon" in data:
            favicon = build / data["favicon"]
            if not favicon.exists():
                shutil.copy2(directory / data["favicon"], favicon)
                check_call(("chmod", "+r", str(favicon)))

        images = build / "images"
        images.mkdir(exist_ok=True)

        pages = []
        all_blog_pages = []

        sections = {}
        all_images = {}
        all_tags = {}
        tag_paths = {}

        users = None
        if user_file.exists():
            with user_file.open("r") as stream:
                users = json.load(stream)

            pages.append(Page("commenting.html", "commenting.html", "Commenting", {}))

        async def process_image(id_or_image) -> dict:
            if isinstance(id_or_image, int):
                image_id = id_or_image
                image = None
            else:
                image_id = id_or_image.id
                image = id_or_image

            if image_id in all_images:
                return all_images[image_id]

            if image is None:
                image = await api.get_image(image_id, tags=True)

            if image is None or not image.full_path:
                print(f"can't find image: {image_id}")
                exit(1)

            extension = image.full_path.suffix.lower()

            image_file = images / f"{image.id}{extension}"

            if not image_file.exists():
                shutil.copy2(image.full_path, image_file)
                check_call(("chmod", "+r", str(image_file)))

            date = image.creation_date.strftime("%Y-%m-%d")
            if image.exif:
                if "DateTimeOriginal" in image.exif:
                    date = image.exif["DateTimeOriginal"].split(" ", 1)[0].replace(
                        ":", "-"
                    )

            row = connection.execute(
                "SELECT date FROM images WHERE image = ?;", (image.id,)
            ).fetchone()
            if row is not None:
                (date,) = row

            tags = []
            for tag in image.tags:
                while tag:
                    row = connection.execute(
                        "SELECT display FROM tags WHERE tag = ?;", (tag,)
                    ).fetchone()

                    if row is None:
                        allowed = None
                        while allowed is None:
                            response = input(f"allow #{tag}? y/n\n")
                            if response == "y":
                                allowed = True
                            elif response == "n":
                                allowed = False
                            else:
                                print("please type 'y' or 'n'")

                        connection.execute(
                            "INSERT INTO tags (tag, display) VALUES (?, ?);",
                            (tag, allowed),
                        )
                        connection.commit()
                    else:
                        (allowed,) = row

                    if allowed:
                        tags.append(tag.split("/"))

                        while tag:
                            if tag not in all_tags:
                                all_tags[tag] = [image_id]

                                parts = []
                                for symbol in tag:
                                    if symbol.isalnum() and symbol.isascii():
                                        parts.append(symbol.lower())
                                    elif symbol == "/":
                                        parts.append("_")
                                    elif symbol in ".-":
                                        parts.append(symbol)
                                    else:
                                        parts.append("-")
                                tag_paths[tag] = "".join(parts)
                            else:
                                all_tags[tag].append(image_id)

                            if "/" in tag:
                                tag = tag.rsplit("/", 1)[0]
                            else:
                                tag = None
                    else:
                        if "/" in tag:
                            tag = tag.rsplit("/", 1)[0]
                        else:
                            tag = None

            image_data = {
                "id": image.id,
                "date": date,
                "datetime": image.creation_date,
                "image": {
                    "title": image.title,
                    "alt": image.alt,
                    "caption": image.caption,
                    "timestamp": image.creation_date.timestamp(),
                },
                "file": image_file.name,
                "tags": tags,
            }
            all_images[image.id] = image_data

            return image_data

        template = ENVIRONMENT.get_template("style.css")
        with (build / "style.css").open("w") as stream:
            stream.write(template.render(colours=data["colours"]))

        connection = sqlite3.connect(database)
        api = load(args.config)

        for path in directory.iterdir():
            if path.name.startswith("blog-"):
                entries = []

                blog_config = path / "config.json"
                with blog_config.open("r") as stream:
                    blog_data = json.load(stream)

                entries = []
                previous = None

                comments = blog_data.get("comments", {})

                for post_path in sorted(path.iterdir(), key=lambda f: f.name):
                    if not post_path.stem.isnumeric():
                        continue

                    with post_path.open("r") as stream:
                        post_data = json.load(stream)

                    post_data["slug"] = f'{post_data["slug"]}.html'

                    post_data["comments"] = comments.pop(post_data["slug"], [])

                    post_images = []
                    tags = set()
                    for image_id in post_data["images"]:
                        image_data = await process_image(image_id)
                        post_images.append(image_data)
                        for tag in image_data["tags"]:
                            tags.add(tuple(tag))

                    post_data["images"] = post_images
                    post_data["backward"] = previous
                    post_data["forward"] = None
                    post_data["tags"] = tags
                    post_data["datetime"] = datetime.fromtimestamp(
                        int(post_path.stem)
                    ).astimezone()
                    post_data["date"] = post_data["datetime"].strftime("%Y-%m-%d")

                    if entries:
                        entries[-1]["forward"] = post_data["slug"]

                    entries.append(post_data)
                    previous = post_data["slug"]

                if comments:
                    print(f"Unused comments: {', '.join(comments.keys())}")

                blog_pages = []
                for entry in entries:
                    page = Page(
                        "/".join((blog_data["slug"], entry["slug"])),
                        "post.html",
                        entry["title"],
                        {**entry, "tag_paths": tag_paths},
                        date=entry["datetime"],
                    )
                    pages.append(page)
                    blog_pages.append(page)
                    all_blog_pages.append(page)

                page = Page(
                    f'{blog_data["slug"]}/{"index.html"}',
                    "section.html",
                    blog_data["title"],
                    {**blog_data, "entries": entries},
                    section=True,
                )
                pages.append(page)
                page.render_feeds(args.domain, build, blog_pages)

                sections[blog_data["title"]] = blog_data

            if path.name.startswith("section-"):
                with path.open("r") as stream:
                    section_data = json.load(stream)

                if section_data.get("min-rating") is not None:
                    raise NotImplementedError("oops")

                entries = []
                dates = set()
                previous = None

                comments = section_data.get("comments", {})

                for image in await api.search_images(
                    all_tags=section_data["all-tags"],
                    no_tags=section_data["no-tags"],
                    order=["creation_date"],
                ):
                    # for now we're assuming all images are fine

                    if not image.full_path:
                        continue

                    image_data = await process_image(image)
                    date = image_data["date"]
                    if date in dates:
                        slug = f"{date}-{image_data['id']}.html"
                    else:
                        slug = f"{date}.html"
                        dates.add(date)

                    if entries:
                        entries[-1]["forward"] = slug

                    entries.append(
                        {
                            "slug": slug,
                            "date": date,
                            "title": (
                                image_data["image"]["title"] or section_data["title"]
                            ),
                            "images": [image_data],
                            "tags": image_data["tags"],
                            "backward": previous,
                            "forward": None,
                            "comments": comments.pop(slug.rsplit(".", 1)[0], []),
                        }
                    )
                    previous = slug

                if comments:
                    print(f"Unused comments: {', '.join(comments.keys())}")

                blog_pages = []
                for entry in entries:
                    page = Page(
                        "/".join((section_data["slug"], entry["slug"])),
                        "post.html",
                        entry["title"],
                        {**entry, "tag_paths": tag_paths},
                        date=entry["images"][0]["datetime"],
                    )
                    pages.append(page)
                    blog_pages.append(page)
                    all_blog_pages.append(page)

                page = Page(
                    f'{section_data["slug"]}/index.html',
                    "section.html",
                    section_data["title"],
                    {**section_data, "entries": entries},
                    section=True,
                )
                pages.append(page)
                page.render_feeds(args.domain, build, blog_pages)

                sections[section_data["title"]] = section_data

        tag_tree = {}
        for tag, info in all_tags.items():
            entries = []
            for image_id in info:
                image_info = all_images[image_id]
                entries.append(
                    {
                        "slug": f"../images/{image_id}.html",
                        "title": image_info["image"]["title"],
                        "date": image_info["date"],
                        "timestamp": image_info["image"]["timestamp"],
                    }
                )

            pages.append(
                Page(
                    f"tags/{tag_paths[tag]}.html",
                    "section.html",
                    tag,
                    {"entries": sorted(entries, key=lambda e: e["timestamp"])},
                )
            )

            current = tag_tree
            full = []
            for part in tag.split("/"):
                full.append(part)
                if part not in current:
                    current[part] = {"path": tag_paths["/".join(full)], "children": {}}
                current = current[part]["children"]

        pages.append(
            Page(
                "tags/index.html",
                "tags.html",
                "Tags",
                {"tags": tag_tree, "icon": "#️⃣"},
                section=True,
            )
        )

        for info in all_images.values():
            title = info["image"]["title"] or "Untitled"
            pages.append(
                Page(
                    f"images/{info['id']}.html",
                    "post.html",
                    title,
                    {
                        "date": info["date"],
                        "tags": info["tags"],
                        "images": [info],
                        "tag_paths": tag_paths,
                    }
                )
            )

        page = Page("index.html", "home.html", data["name"], {"sections": sections})
        pages.append(page)
        page.render_feeds(args.domain, build, all_blog_pages)

        navbar = []
        for page in sorted(
            (page for page in pages if page.section), key=lambda p: p.relative
        ):
            if "icon" in page.arguments:
                title = f"{page.arguments['icon']} {page.title}"
            else:
                title = page.title

            navbar.append((page.relative, title))

        for page in pages:
            page.render(
                build,
                navbar=navbar,
                users=users,
                domain=args.domain,
            )
    else:
        print(f"Unknown command: {args.command}")


def parse_date(datestr: str) -> int:
    date_format = "%Y-%m-%d %H:%M" if " " in datestr else "%Y-%m-%d"

    return int(datetime.strptime(datestr, date_format).astimezone().timestamp())


if __name__ == '__main__':
    main()

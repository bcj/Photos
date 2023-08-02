# Photos

A photo blog built on top of [PicPocket](https://github.com/bcj/PicPocket)


# Would I Recommend Using This?

**No**. I am making changes to this as I need features and am manually my config files as necessary.
The goal is pull [saved searches](https://github.com/bcj/PicPocket/issues/31) and [collections](https://github.com/bcj/PicPocket/issues/32) into PicPocket so posts can be largely if not completely created within PicPocket itself.

If you are using this, make sure to read the commits to see what's changed.

# Installation

It's assumed you have the newest version of PicPocket installed.
This script uses the same version of python and has (a subset of) the same dependencies.

If you have PicPocket installed and your collection configured, all you need to do is clone this repository to your computer and run `photos.py`.

**NOTE**: That's a lie, you also need to install jinja2:

```sh
pip3 install jinja2
```

## Configuration

This script will store its settings in the same directory as your PicPocket configuration (specifically, in a subdirectory named `site-[domain]`, so you can have multiple photo sites). By default, that means in `~/.config/picpocket`

# Usage

Features are being added to this script as I need them.
This means that a bunch of options and actions don't have nice ways to undo them.
Sorry.

This script currently supports the following:
* sections based on tag searches

## Initial Setup

To create the configuration for the site, run the `initialize` command, telling it where you want to build the site:

```sh
./photos.py [domain] initialize [build directory]
```

This will create a configuration file (this is where the colour scheme is stored), and a database that will store any extra information about photos required.

### Single Photo Collections

This type of blog was written with a 'photo a day' blog in mind and bases page names on dates instead of image ids.
It will break (change what photo is at a given URL) if both of the following are true:
* multiple photos are returned that were taken the same day
* an earlier photo from a given day didn't appear in a search until after a later photo from that day did.

If that's all fine with you

```sh
./photos.py [domain] create-auto [section title]
```

There are also a bunch of optional flags but you'll probably want to pass most if not all of them:
* `--slug [slug]`: Where this section will be accessible (the root will be at `[domain]/[slug]/index.html`). If this isn't given, The script will auto-generate this from the title by converting it to a safe version of the name
* `--description [description]`: A short text description of the section. This will appear on the index for that page
* `--creators [creator...]`: Only include images that have one of these people listed as their creator
* `--all-tags [tag...]`: Only include images with all of these tags
* `--no-tags [tag...]`: Only include images with none of these tags
* `--icon [emoji]`: An emoji to use as a symbol to represent this page

Once you've made this section, it will update every time you build your site.

### Photo Blogs

This type of blog includes multiple photos per page

```sh
./photos.py [domain] create-blog [section title]
```

There are also some similar options to an auto-blog:
* `--slug [slug]`: Where this section will be accessible (the root will be at `[domain]/[slug]/index.html`). If this isn't given, The script will auto-generate this from the title by converting it to a safe version of the name
* `--description [description]`: A short text description of the section. This will appear on the index for that page
* `--icon [emoji]`: An emoji to use as a symbol to represent this page

## Making Blog Posts

```sh
./photos.py [domain] post [blog] [title]
```

Where `blog` is the slug of a photo blog you already created.

There are also a bunch of optional flags but you'll probably want to pass most if not all of them:
* `--slug [slug]`: Where this section will be accessible (the root will be at `[domain]/[blog]/[slug].html`).
* `--description [description]`: Text to put at the top of the page
* `--image [id...]`: The PicPocket ids of images to include in the post
* `--date [DATE]`: The date of the post (either `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`). If not given, the current time will be used

You'll need to build the site for posts to show up.

## Building your site

This will build your site.

```sh
./photos.py [domain] build
```

Pass `--fresh` if you want to clear the build directory first.